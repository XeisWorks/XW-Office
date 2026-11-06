"""Isolated Outlook desktop mail composer.

Run this module in a subprocess. Outlook COM can block while Outlook starts,
loads profiles, or opens an inspector; isolating it keeps the PySide UI thread
responsive and lets callers enforce a timeout.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote


_OL_MAIL_ITEM = 0
_OL_FOLDER_DRAFTS = 16
_DISPID_SEND_USING_ACCOUNT = 64209


class OutlookComposeError(RuntimeError):
    """Raised when Outlook cannot prepare the requested draft."""


def open_classic_outlook_draft(
    *,
    to_email: str,
    subject: str,
    outlook_executable: str | Path | None = None,
) -> dict[str, str]:
    """Open a prefilled draft through Outlook Classic's supported CLI.

    This path deliberately avoids COM activation. When Outlook is not already
    running, COM starts ``OUTLOOK.EXE -Embedding`` as a hidden OLE server;
    profile initialization can then block before an Inspector window exists.
    The ``/c ipm.note /m`` switches create an interactive Classic mail window.
    """
    recipient = str(to_email or "").strip()
    if not recipient:
        raise OutlookComposeError("Empfaenger fehlt")

    executable = (
        Path(outlook_executable).expanduser()
        if outlook_executable is not None
        else _find_classic_outlook_executable()
    )
    if not executable.is_file():
        raise OutlookComposeError(f"Outlook Classic nicht gefunden: {executable}")

    message_target = quote(recipient, safe="@._+-")
    clean_subject = str(subject or "").strip()
    if clean_subject:
        message_target = f"{message_target}?subject={quote(clean_subject, safe='')}"

    try:
        process = subprocess.Popen(  # noqa: S603 - resolved executable is validated above
            [str(executable), "/c", "ipm.note", "/m", message_target],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        raise OutlookComposeError(f"Outlook Classic konnte nicht gestartet werden: {exc}") from exc
    return {"pid": str(process.pid), "executable": str(executable)}


def _find_classic_outlook_executable() -> Path:
    """Resolve the registered Outlook Classic executable without launching it."""
    candidates = _registered_outlook_executables()

    on_path = shutil.which("OUTLOOK.EXE") or shutil.which("outlook.exe")
    if on_path:
        candidates.append(Path(on_path))

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = str(os.environ.get(env_name) or "").strip()
        if not root:
            continue
        for office_version in ("Office16", "Office15", "Office14"):
            candidates.append(
                Path(root) / "Microsoft Office" / "root" / office_version / "OUTLOOK.EXE"
            )
            candidates.append(Path(root) / "Microsoft Office" / office_version / "OUTLOOK.EXE")

    for candidate in candidates:
        try:
            resolved = candidate.expanduser()
            if resolved.is_file() and resolved.name.casefold() == "outlook.exe":
                return resolved
        except OSError:
            continue
    raise OutlookComposeError(
        "Outlook Classic wurde nicht gefunden. Bitte Outlook Classic installieren oder reparieren."
    )


def _registered_outlook_executables() -> list[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE"
    candidates: list[Path] = []
    views = (
        getattr(winreg, "KEY_WOW64_64KEY", 0),
        getattr(winreg, "KEY_WOW64_32KEY", 0),
    )
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in dict.fromkeys(views):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                    value = str(winreg.QueryValue(key, None) or "").strip().strip('"')
            except OSError:
                continue
            if value:
                candidates.append(Path(value))
    return candidates


def compose_outlook_mail(
    *,
    to_email: str,
    subject: str,
    sender_smtp: str,
    body: str = "",
    html_body: str = "",
    attachments: list[str] | None = None,
) -> dict[str, str]:
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
        _apply_body(mail, body, html_body=html_body)
        _apply_attachments(mail, attachments or [])
        save = getattr(mail, "Save", None)
        if callable(save):
            save()
        return {
            "entry_id": str(getattr(mail, "EntryID", "") or "").strip(),
            "store_id": str(getattr(getattr(mail, "Parent", None), "StoreID", "") or "").strip(),
        }
    finally:
        pythoncom.CoUninitialize()


def reopen_outlook_mail(*, entry_id: str, store_id: str = "") -> None:
    """Open a previously saved draft by its stable Outlook identifiers."""
    wanted_entry = str(entry_id or "").strip()
    if not wanted_entry:
        raise OutlookComposeError("Outlook-Entwurf-ID fehlt")
    import pythoncom
    import win32com.client as win32

    pythoncom.CoInitialize()
    try:
        outlook = win32.Dispatch("Outlook.Application")
        item = outlook.Session.GetItemFromID(wanted_entry, str(store_id or "").strip() or None)
        item.Display(False)
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


def _apply_body(mail: Any, body: str, *, html_body: str = "") -> None:
    clean_html = str(html_body or "").strip()
    if clean_html:
        # Replace the default signature inserted by Outlook during Display().
        mail.HTMLBody = clean_html
        return
    clean_body = str(body or "").strip()
    if not clean_body:
        return
    try:
        existing = str(getattr(mail, "Body", "") or "")
        mail.Body = f"{clean_body}\n\n{existing}".rstrip()
    except Exception:
        mail.Body = clean_body


def _apply_attachments(mail: Any, attachments: list[str]) -> None:
    for raw_path in attachments:
        path = Path(str(raw_path or "").strip()).expanduser()
        if not path.is_file():
            raise OutlookComposeError(f"Anhang nicht gefunden: {path}")
        mail.Attachments.Add(str(path.resolve()))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if str(payload.get("operation") or "compose").strip().lower() == "reopen":
            reopen_outlook_mail(
                entry_id=str(payload.get("entry_id") or ""),
                store_id=str(payload.get("store_id") or ""),
            )
            print(json.dumps({"ok": True}))
            return 0
        result = compose_outlook_mail(
            to_email=str(payload.get("to") or ""),
            subject=str(payload.get("subject") or ""),
            sender_smtp=str(payload.get("sender") or ""),
            body=str(payload.get("body") or ""),
            html_body=str(payload.get("html_body") or ""),
            attachments=[
                str(item)
                for item in (payload.get("attachments") or [])
                if str(item or "").strip()
            ],
        )
        print(json.dumps({"ok": True, **result}))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc), "type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
