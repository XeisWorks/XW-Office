from __future__ import annotations

from threading import Event

from PySide6.QtCore import QTimer
from PySide6.QtGui import QDesktopServices

from xw_office.services.flow_api import FlowRefundsClient
from xw_office.services.sevdesk.refund_client import SevDeskRefundClient
from xw_office.ui.modules.rechnungen.refunds_dialog import RefundsDialog


class _Container:
    def __init__(self, flow: object, sevdesk: object) -> None:
        self.flow = flow
        self.sevdesk = sevdesk

    def resolve(self, service_type: object) -> object:
        if service_type is FlowRefundsClient:
            return self.flow
        if service_type is SevDeskRefundClient:
            return self.sevdesk
        raise KeyError(service_type)


def test_refund_list_and_pdf_io_do_not_block_event_loop(qtbot, monkeypatch) -> None:
    list_started = Event()
    pdf_started = Event()
    release = Event()

    class Flow:
        def list_refunds(self, *, limit: int):
            assert limit == 250
            list_started.set()
            release.wait(2)
            return [
                {
                    "wix_refund_id": "refund-1",
                    "process_status": "done_creditnote",
                    "sevdesk_credit_note_id": "credit-1",
                }
            ]

    class Sevdesk:
        def get_credit_note_pdf(self, credit_note_id: str) -> bytes:
            assert credit_note_id == "credit-1"
            pdf_started.set()
            release.wait(2)
            return b"%PDF-1.4 test"

    monkeypatch.setattr(QDesktopServices, "openUrl", lambda *_args: True)
    dialog = RefundsDialog(_Container(Flow(), Sevdesk()))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    beats: list[int] = []
    QTimer.singleShot(20, lambda: beats.append(1))
    qtbot.waitUntil(list_started.is_set, timeout=1000)
    qtbot.waitUntil(lambda: bool(beats), timeout=1000)
    assert dialog._table.isEnabled() is False  # noqa: SLF001

    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
    assert dialog._table.rowCount() == 1  # noqa: SLF001
    release.clear()
    dialog._open_pdf(0)  # noqa: SLF001
    qtbot.waitUntil(pdf_started.is_set, timeout=1000)
    beats.clear()
    QTimer.singleShot(20, lambda: beats.append(2))
    qtbot.waitUntil(lambda: bool(beats), timeout=1000)
    assert dialog._table.isEnabled() is False  # noqa: SLF001
    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
