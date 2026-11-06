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
import time
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
    sender_smtp: str = "",
    outlook_executable: str | Path | None = None,
) -> dict[str, str]:
    """Open a prefilled Outlook Classic draft and select its sender account.

    The supported ``/c ipm.note /m`` switches first create the interactive
    Classic mail window. If *sender_smtp* is provided, a bounded helper then
    attaches only to that already-running Outlook instance and applies
    ``SendUsingAccount``. It never starts Outlook through COM.
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

    launched_at_epoch = time.time()
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

    result = {"pid": str(process.pid), "executable": str(executable)}
    sender = str(sender_smtp or "").strip()
    if not sender:
        return result

    sender_result = _apply_sender_in_helper(
        to_email=recipient,
        subject=clean_subject,
        sender_smtp=sender,
        not_before_epoch=launched_at_epoch - 2.0,
    )
    return {**result, **sender_result}


def _apply_sender_in_helper(
    *,
    to_email: str,
    subject: str,
    sender_smtp: str,
    not_before_epoch: float,
) -> dict[str, str]:
    payload = json.dumps(
        {
            "operation": "select_sender",
            "to": to_email,
            "subject": subject,
            "sender": sender_smtp,
            "wait_seconds": 25,
            "not_before_epoch": not_before_epoch,
        },
        ensure_ascii=False,
    )
    env = dict(os.environ)
    src_path = str(Path(__file__).resolve().parents[3])
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{src_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else src_path
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "xw_office.services.mailing.outlook_compose"],
            input=payload,
            text=True,
            capture_output=True,
            timeout=30,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OutlookComposeError(
            f"Absenderkonto konnte nicht rechtzeitig gesetzt werden: {sender_smtp}"
        ) from exc

    try:
        decoded = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        decoded = {}
    if completed.returncode != 0 or not decoded.get("ok"):
        error = str(decoded.get("error") or completed.stderr or completed.stdout or "").strip()
        raise OutlookComposeError(error or f"Absenderkonto konnte nicht gesetzt werden: {sender_smtp}")
    return {
        "sender": str(decoded.get("sender") or sender_smtp).strip(),
        "entry_id": str(decoded.get("entry_id") or "").strip(),
    }


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


def select_outlook_draft_sender(
    *,
    sender_smtp: str,
    to_email: str,
    subject: str,
    wait_seconds: float = 25,
    not_before_epoch: float = 0,
) -> dict[str, str]:
    """Apply a sender account to a draft opened by the Classic CLI.

    ``GetActiveObject`` is intentional: unlike ``Dispatch``, it cannot launch
    Outlook as a hidden ``-Embedding`` server while the interactive client is
    still starting.
    """
    sender = str(sender_smtp or "").strip()
    if not sender:
        raise OutlookComposeError("OUTLOOK_SENDER_EMAIL fehlt")

    import pythoncom
    import win32com.client as win32

    deadline = time.monotonic() + max(1.0, float(wait_seconds))
    pythoncom.CoInitialize()
    try:
        while time.monotonic() < deadline:
            try:
                outlook = win32.GetActiveObject("Outlook.Application")
                result = _apply_sender_to_matching_draft(
                    outlook,
                    sender_smtp=sender,
                    to_email=to_email,
                    subject=subject,
                    not_before_epoch=not_before_epoch,
                )
                if result is not None:
                    return result
            except OutlookComposeError:
                raise
            except Exception:
                # Outlook may be registered before its profile and Inspectors
                # collection are ready. Retry without creating another instance.
                pass
            pump = getattr(pythoncom, "PumpWaitingMessages", None)
            if callable(pump):
                pump()
            time.sleep(0.2)
    finally:
        pythoncom.CoUninitialize()

    raise OutlookComposeError(
        "Der Outlook-Entwurf oder das Absenderkonto wurde nicht gefunden: "
        f"{sender}"
    )


def _apply_sender_to_matching_draft(
    outlook: Any,
    *,
    sender_smtp: str,
    to_email: str,
    subject: str,
    not_before_epoch: float = 0,
) -> dict[str, str] | None:
    account = _find_account(outlook.Session.Accounts, sender_smtp)
    if account is None:
        return None

    for inspector in _outlook_inspectors(outlook):
        try:
            mail = inspector.CurrentItem
            if not _draft_matches(
                mail,
                to_email=to_email,
                subject=subject,
                not_before_epoch=not_before_epoch,
            ):
                continue
            _apply_sender(mail, account)
            selected_account = getattr(mail, "SendUsingAccount", None)
            if not _account_matches(selected_account, sender_smtp.casefold()):
                raise OutlookComposeError(
                    f"Outlook hat das Absenderkonto nicht übernommen: {sender_smtp}"
                )
            save = getattr(mail, "Save", None)
            if callable(save):
                save()
            try:
                inspector.WindowState = 2  # olNormalWindow
            except Exception:
                pass
            activate = getattr(inspector, "Activate", None)
            if callable(activate):
                activate()
            return {
                "sender": str(getattr(account, "SmtpAddress", sender_smtp) or sender_smtp),
                "entry_id": str(getattr(mail, "EntryID", "") or "").strip(),
            }
        except OutlookComposeError:
            raise
        except Exception:
            continue
    return None


def _outlook_inspectors(outlook: Any) -> list[Any]:
    inspectors: list[Any] = []
    try:
        active = outlook.ActiveInspector()
        if active is not None:
            inspectors.append(active)
    except Exception:
        pass

    try:
        collection = outlook.Inspectors
        count = int(getattr(collection, "Count", 0) or 0)
    except Exception:
        return inspectors
    for idx in range(count, 0, -1):
        try:
            inspector = collection.Item(idx)
        except Exception:
            continue
        if inspector is not None:
            inspectors.append(inspector)
    return inspectors


def _draft_matches(
    mail: Any,
    *,
    to_email: str,
    subject: str,
    not_before_epoch: float = 0,
) -> bool:
    if not_before_epoch:
        try:
            created_epoch = float(mail.CreationTime.timestamp())
        except Exception:
            return False
        if created_epoch < not_before_epoch:
            return False
    wanted_subject = str(subject or "").strip()
    actual_subject = str(getattr(mail, "Subject", "") or "").strip()
    if wanted_subject:
        return actual_subject == wanted_subject
    wanted_recipient = str(to_email or "").strip().casefold()
    actual_recipient = str(getattr(mail, "To", "") or "").strip().casefold()
    return bool(wanted_recipient and wanted_recipient in actual_recipient)


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
        operation = str(payload.get("operation") or "compose").strip().lower()
        if operation == "reopen":
            reopen_outlook_mail(
                entry_id=str(payload.get("entry_id") or ""),
                store_id=str(payload.get("store_id") or ""),
            )
            print(json.dumps({"ok": True}))
            return 0
        if operation == "select_sender":
            result = select_outlook_draft_sender(
                sender_smtp=str(payload.get("sender") or ""),
                to_email=str(payload.get("to") or ""),
                subject=str(payload.get("subject") or ""),
                wait_seconds=float(payload.get("wait_seconds") or 25),
                not_before_epoch=float(payload.get("not_before_epoch") or 0),
            )
            print(json.dumps({"ok": True, **result}))
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
