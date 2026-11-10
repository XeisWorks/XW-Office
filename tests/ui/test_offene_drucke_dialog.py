"""Attachment selection regressions with delayed, fake mailbox responses."""

from __future__ import annotations

from threading import Event
from pytestqt.qtbot import QtBot

from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.services.drucke.service import OffeneDruckeService, PrintAttachment, PrintCase
from xw_office.ui.modules.rechnungen.offene_drucke_dialog import OffeneDruckeDialog


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
