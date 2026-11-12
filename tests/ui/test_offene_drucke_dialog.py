"""Attachment selection regressions with delayed, fake mailbox responses."""

from __future__ import annotations

from pathlib import Path
from threading import Event, current_thread
from PySide6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.services.drucke.service import OffeneDruckeService, PrintAttachment, PrintCase
from xw_office.ui.modules.rechnungen.offene_drucke_dialog import OffeneDruckeDialog


def test_mailbox_service_resolution_runs_off_ui_thread(qtbot: QtBot) -> None:
    entered, release = Event(), Event()

    class Mailbox:
        def refresh_from_graph(self) -> list[PrintCase]:
            return [PrintCase("a", "A", "", "", "graph_mail", "a")]

        def last_flow_sync_error(self) -> str:
            return ""

    class SlowContainer:
        def resolve(self, service_type: object) -> object:
            assert service_type is OffeneDruckeService
            entered.set()
            release.wait(2)
            return Mailbox()

    dialog = OffeneDruckeDialog(SlowContainer())  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    beats: list[bool] = []
    QTimer.singleShot(20, lambda: beats.append(True))
    qtbot.waitUntil(entered.is_set, timeout=1000)
    qtbot.waitUntil(lambda: bool(beats), timeout=1000)
    assert "OPEN PRINTS" in dialog._status.text()  # noqa: SLF001
    release.set()
    qtbot.waitUntil(lambda: dialog._list.count() == 1, timeout=1000)  # noqa: SLF001


def test_attachment_file_validation_runs_off_ui_thread(qtbot: QtBot, monkeypatch, tmp_path) -> None:
    main_thread = current_thread()
    target = tmp_path / "invoice.pdf"
    target.write_bytes(b"%PDF-1.7")
    checked_threads: list[object] = []
    opened: list[str] = []
    original_is_file = Path.is_file

    def tracked_is_file(path: Path) -> bool:
        if path == target:
            checked_threads.append(current_thread())
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", tracked_is_file)
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.offene_drucke_dialog.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    class Mailbox:
        def refresh_from_graph(self) -> list[PrintCase]:
            return [PrintCase("a", "A", "", "", "graph_mail", "a")]

        def last_flow_sync_error(self) -> str:
            return ""

        def list_attachments(self, _case_id: str) -> list[PrintAttachment]:
            return [PrintAttachment("attachment", "invoice.pdf", "application/pdf", 8)]

        def download_attachment_to_cache(
            self, _case_id: str, _attachment_id: str, _filename: str
        ) -> Path:
            return target

    container = Container(AppConfig())
    container.register(OffeneDruckeService, lambda _: Mailbox())
    dialog = OffeneDruckeDialog(container)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._attachment_list.count() == 1)
    dialog._attachment_list.setCurrentRow(0)
    dialog._open_attachment()
    qtbot.waitUntil(lambda: bool(opened))

    assert checked_threads
    assert all(thread is not main_thread for thread in checked_threads)
    assert len(opened) == 1
    assert Path(opened[0]) == target


def test_attachment_reply_matches_latest_case_after_rapid_selection(qtbot: QtBot) -> None:
    entered, release = Event(), Event()
    calls: list[str] = []

    class Mailbox:
        def refresh_from_graph(self) -> list[PrintCase]:
            return [PrintCase(key, key, "", "", "graph_mail", key) for key in ("a", "b", "c")]

        def last_flow_sync_error(self) -> str:
            return ""

        def list_attachments(self, case_id: str) -> list[PrintAttachment]:
            calls.append(case_id)
            if case_id == "a":
                entered.set()
                assert release.wait(3)
            return [PrintAttachment(case_id, f"{case_id}.pdf", "application/pdf", 1)]

    container = Container(AppConfig())
    container.register(OffeneDruckeService, lambda _: Mailbox())
    dialog = OffeneDruckeDialog(container)
    qtbot.addWidget(dialog)
    try:
        qtbot.waitUntil(entered.is_set)
        dialog._list.setCurrentRow(1)
        dialog._list.setCurrentRow(2)
        assert dialog._attachments == []
        assert not dialog._open_attachment_button.isEnabled()
    finally:
        release.set()
        qtbot.waitUntil(lambda: dialog._attachment_worker is None)
    assert calls == ["a", "c"]
    assert [attachment.name for attachment in dialog._attachments] == ["c.pdf"]
    assert dialog._attachment_list.item(0).text().startswith("c.pdf")


def test_mark_done_does_not_block_event_loop_or_repeat(qtbot: QtBot) -> None:
    entered, release = Event(), Event()
    calls: list[str] = []

    class Mailbox:
        def refresh_from_graph(self) -> list[PrintCase]:
            return [PrintCase("a", "A", "", "", "graph_mail", "a")]

        def last_flow_sync_error(self) -> str:
            return ""

        def list_attachments(self, _case_id: str) -> list[PrintAttachment]:
            return []

        def mark_done(self, case_id: str, *, done: bool) -> None:
            assert done is True
            calls.append(case_id)
            entered.set()
            assert release.wait(3)

    container = Container(AppConfig())
    container.register(OffeneDruckeService, lambda _: Mailbox())
    dialog = OffeneDruckeDialog(container)
    qtbot.addWidget(dialog)
    try:
        qtbot.waitUntil(lambda: dialog._list.count() == 1)
        dialog._mark_done()
        qtbot.waitUntil(entered.is_set)
        assert not dialog._done.isEnabled()
        dialog._mark_done()
        assert calls == ["a"]
        beats: list[bool] = []
        QTimer.singleShot(20, lambda: beats.append(True))
        qtbot.waitUntil(lambda: bool(beats))
    finally:
        release.set()
        qtbot.waitUntil(lambda: dialog._action_worker is None)
    assert calls == ["a"]
    assert dialog._list.count() == 0


def test_close_while_mark_done_runs_waits_for_write_result(qtbot: QtBot) -> None:
    entered, release = Event(), Event()

    class Mailbox:
        def refresh_from_graph(self) -> list[PrintCase]:
            return [PrintCase("a", "A", "", "", "graph_mail", "a")]

        def last_flow_sync_error(self) -> str:
            return ""

        def list_attachments(self, _case_id: str) -> list[PrintAttachment]:
            return []

        def mark_done(self, _case_id: str, *, done: bool) -> None:
            assert done is True
            entered.set()
            assert release.wait(3)

    container = Container(AppConfig())
    container.register(OffeneDruckeService, lambda _: Mailbox())
    dialog = OffeneDruckeDialog(container)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._list.count() == 1)
    dialog._mark_done()
    qtbot.waitUntil(entered.is_set)
    dialog.reject()
    dialog.close()
    assert dialog.isVisible()

    release.set()
    qtbot.waitUntil(lambda: dialog._action_worker is None)
    assert dialog._list.count() == 0
    assert dialog.isVisible()

    dialog.reject()
    assert not dialog.isVisible()
