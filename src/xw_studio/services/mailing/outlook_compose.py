"""Isolated Outlook desktop mail composer.

Run this module in a subprocess. Outlook COM can block while Outlook starts,
loads profiles, or opens an inspector; isolating it keeps the PySide UI thread
responsive and lets callers enforce a timeout.
"""
from __future__ import annotations

import json
import sys
from typing import Any


_OL_MAIL_ITEM = 0
_OL_FOLDER_DRAFTS = 16
_DISPID_SEND_USING_ACCOUNT = 64209


class OutlookComposeError(RuntimeError):
    """Raised when Outlook cannot prepare the requested draft."""


def compose_outlook_mail(*, to_email: str, subject: str, sender_smtp: str) -> None:
    """Open an editable Outlook mail draft from *sender_smtp*."""
    sender = str(sender_smtp or "").strip()
    recipient = str(to_email or "").strip()
    if not sender:
        raise OutlookComposeError("OUTLOOK_SENDER_EMAIL fehlt")
    if not recipient:
        raise OutlookComposeError("Empfaenger fehlt")

    import pythoncom  # type: ignore[import-untyped]
    import win32com.client as win32  # type: ignore[import-untyped]

    pythoncom.CoInitialize()
    try:
        outlook = win32.Dispatch("Outlook.Application")
        account = _find_account(outlook.Session.Accounts, sender)
        if account is None:
            raise OutlookComposeError(f"Outlook-Konto nicht gefunden: {sender}")

        mail = _create_mail_item(outlook, account)
        mail.To = recipient
        mail.Subject = str(subject or "").strip()
        _apply_sender(mail, account)
        mail.Display(False)
        # Some Outlook builds reset the From account while creating the
        # inspector/signature. Re-apply after Display so the visible From
        # selector is forced to the configured account.
        _apply_sender(mail, account)
    finally:
        pythoncom.CoUninitialize()


def _find_account(accounts: Any, sender_smtp: str) -> Any | None:
    wanted = str(sender_smtp or "").strip().lower()
    if not wanted:
        return None

    try:
        for account in accounts:
            if _account_matches(account, wanted):
                return account
    except Exception:
        pass

    try:
        count = int(getattr(accounts, "Count", 0) or 0)
    except Exception:
        count = 0
    for idx in range(1, count + 1):
        try:
            account = accounts.Item(idx)
        except Exception:
            continue
        if _account_matches(account, wanted):
            return account
    return None


def _create_mail_item(outlook: Any, account: Any) -> Any:
    """Create a mail item in the target account's Drafts folder when possible."""
    try:
        store = getattr(account, "DeliveryStore", None)
        if store is not None:
            drafts = store.GetDefaultFolder(_OL_FOLDER_DRAFTS)
            items = getattr(drafts, "Items", None)
            if items is not None:
                return items.Add("IPM.Note")
    except Exception:
        pass
    return outlook.CreateItem(_OL_MAIL_ITEM)


def _account_matches(account: Any, wanted: str) -> bool:
    return any(
        str(getattr(account, attr, "") or "").strip().lower() == wanted
        for attr in ("SmtpAddress", "DisplayName", "UserName")
    )


def _apply_sender(mail: Any, account: Any) -> None:
    mail.SendUsingAccount = account
    ole = getattr(mail, "_oleobj_", None)
    if ole is not None:
        try:
            ole.Invoke(_DISPID_SEND_USING_ACCOUNT, 0, 8, 0, account)
        except Exception:
            pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        compose_outlook_mail(
            to_email=str(payload.get("to") or ""),
            subject=str(payload.get("subject") or ""),
            sender_smtp=str(payload.get("sender") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc), "type": type(exc).__name__}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
