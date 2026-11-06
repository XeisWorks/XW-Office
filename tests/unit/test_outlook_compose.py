from __future__ import annotations

import types
import sys
from pathlib import Path

from xw_office.services.mailing import outlook_compose


def test_open_classic_outlook_draft_uses_interactive_classic_cli(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "OUTLOOK.EXE"
    executable.write_bytes(b"test executable")
    calls: list[dict[str, object]] = []
    helper_calls: list[dict[str, object]] = []

    def fake_popen(command: list[str], **kwargs: object) -> object:
        calls.append({"command": command, **kwargs})
        return types.SimpleNamespace(pid=4711)

    def fake_run(command: list[str], **kwargs: object) -> object:
        helper_calls.append({"command": command, **kwargs})
        return types.SimpleNamespace(
            returncode=0,
            stdout='{"ok": true, "sender": "office@xeisworks.at", "entry_id": "draft-1"}',
            stderr="",
        )

    monkeypatch.setattr(outlook_compose.subprocess, "Popen", fake_popen)  # type: ignore[attr-defined]
    monkeypatch.setattr(outlook_compose.subprocess, "run", fake_run)  # type: ignore[attr-defined]

    result = outlook_compose.open_classic_outlook_draft(
        to_email="kunde@example.test",
        subject="Wix-Order-Nr. 20844 | sevDesk-Rechnungsnr. RE-DRAFT",
        sender_smtp="office@xeisworks.at",
        outlook_executable=executable,
    )

    assert result["pid"] == "4711"
    assert result["sender"] == "office@xeisworks.at"
    command = calls[0]["command"]
    assert command == [str(executable)]
    assert calls[0]["stdin"] is outlook_compose.subprocess.DEVNULL
    assert "creationflags" not in calls[0]
    assert helper_calls
    assert '"operation": "compose"' in str(helper_calls[0]["input"])
    assert '"attach_only": true' in str(helper_calls[0]["input"])
    assert '"sender": "office@xeisworks.at"' in str(helper_calls[0]["input"])


def test_wait_for_running_outlook_never_dispatches_hidden_instance(monkeypatch: object) -> None:
    outlook = object()
    win32 = types.SimpleNamespace(GetActiveObject=lambda _name: outlook)

    assert outlook_compose._wait_for_running_outlook(win32, wait_seconds=1) is outlook  # noqa: SLF001


def test_attached_com_draft_sets_requested_sender_before_and_after_display(
    monkeypatch: object,
) -> None:
    events: list[str] = []
    account = types.SimpleNamespace(
        SmtpAddress="office@xeisworks.at",
        DisplayName="XeisWorks Office",
        UserName="office@xeisworks.at",
    )
    inspector = types.SimpleNamespace(WindowState=1, Activate=lambda: events.append("activate"))

    class _Mail:
        EntryID = "draft-1"
        Parent = types.SimpleNamespace(StoreID="store-1")
        GetInspector = inspector

        def __setattr__(self, name: str, value: object) -> None:
            if name == "SendUsingAccount":
                events.append("sender")
            object.__setattr__(self, name, value)

        def Display(self, _modal: bool) -> None:  # noqa: N802
            events.append("display")

        def Save(self) -> None:  # noqa: N802
            events.append("save")

    mail = _Mail()
    items = types.SimpleNamespace(Add=lambda _message_class: mail)
    account.DeliveryStore = types.SimpleNamespace(
        GetDefaultFolder=lambda _folder_id: types.SimpleNamespace(Items=items)
    )
    outlook = types.SimpleNamespace(Session=types.SimpleNamespace(Accounts=[account]))

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: None  # type: ignore[attr-defined]
    pythoncom.CoUninitialize = lambda: None  # type: ignore[attr-defined]
    win32_client = types.ModuleType("win32com.client")
    win32_client.GetActiveObject = lambda _name: outlook  # type: ignore[attr-defined]
    win32 = types.ModuleType("win32com")
    win32.client = win32_client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32com", win32)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32com.client", win32_client)  # type: ignore[attr-defined]

    result = outlook_compose.compose_outlook_mail(
        to_email="kunde@example.test",
        subject="Kundenmail",
        sender_smtp="office@xeisworks.at",
        attach_only=True,
        wait_seconds=1,
    )

    assert result == {"entry_id": "draft-1", "store_id": "store-1"}
    assert mail.SendUsingAccount is account
    assert events == ["sender", "display", "sender", "save", "activate"]
    assert inspector.WindowState == 2


def test_create_mail_item_prefers_target_account_drafts_folder() -> None:
    created = object()

    class _Items:
        def Add(self, message_class: str) -> object:  # noqa: N802
            assert message_class == "IPM.Note"
            return created

    class _Store:
        def GetDefaultFolder(self, folder_id: int) -> object:  # noqa: N802
            assert folder_id == 16
            return types.SimpleNamespace(Items=_Items())

    account = types.SimpleNamespace(DeliveryStore=_Store())
    outlook = types.SimpleNamespace(CreateItem=lambda _kind: object())

    assert outlook_compose._create_mail_item(outlook, account) is created  # noqa: SLF001


def test_create_mail_item_falls_back_to_default_create_item() -> None:
    fallback = object()
    account = types.SimpleNamespace(DeliveryStore=None)
    outlook = types.SimpleNamespace(CreateItem=lambda kind: fallback if kind == 0 else object())

    assert outlook_compose._create_mail_item(outlook, account) is fallback  # noqa: SLF001


def test_apply_html_body_replaces_outlook_signature() -> None:
    mail = types.SimpleNamespace(
        Body="Old plain signature",
        HTMLBody='<a href="mailto:office@xeisworks.at">old signature</a>',
    )

    outlook_compose._apply_body(mail, "Plain fallback", html_body="<p>Complete custom mail</p>")

    assert mail.HTMLBody == "<p>Complete custom mail</p>"
    assert "mailto:" not in mail.HTMLBody
