from __future__ import annotations

from threading import Event, get_ident

from PySide6.QtCore import QTimer
from PySide6.QtGui import QDesktopServices

from xw_office.services.flow_api import FlowRefundsClient
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.sevdesk.invoice_client import InvoiceClient
from xw_office.services.sevdesk.refund_client import SevDeskRefundClient
from xw_office.services.wix.client import WixOrdersClient
from xw_office.ui.modules.rechnungen.refunds_dialog import RefundsDialog


class _Container:
    def __init__(self, flow: object, sevdesk: object) -> None:
        self.flow = flow
        self.sevdesk = sevdesk
        self.resolve_threads: list[int] = []

    def resolve(self, service_type: object) -> object:
        self.resolve_threads.append(get_ident())
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
    container = _Container(Flow(), Sevdesk())
    ui_thread = get_ident()
    dialog = RefundsDialog(container)  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    beats: list[int] = []
    QTimer.singleShot(20, lambda: beats.append(1))
    qtbot.waitUntil(list_started.is_set, timeout=1000)
    qtbot.waitUntil(lambda: bool(beats), timeout=1000)
    assert dialog._table.isEnabled() is False  # noqa: SLF001

    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
    assert dialog._table.rowCount() == 1  # noqa: SLF001
    assert container.resolve_threads and all(thread != ui_thread for thread in container.resolve_threads)
    release.clear()
    dialog._open_pdf(0)  # noqa: SLF001
    qtbot.waitUntil(pdf_started.is_set, timeout=1000)
    beats.clear()
    QTimer.singleShot(20, lambda: beats.append(2))
    qtbot.waitUntil(lambda: bool(beats), timeout=1000)
    assert dialog._table.isEnabled() is False  # noqa: SLF001
    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
    assert all(thread != ui_thread for thread in container.resolve_threads)


def test_refund_mail_service_resolution_runs_off_ui_thread(qtbot, monkeypatch) -> None:
    entered, release = Event(), Event()
    ui_thread = get_ident()

    class Flow:
        def list_refunds(self, *, limit: int):
            del limit
            return []

    class Sevdesk:
        def fetch_credit_note(self, credit_note_id: str):
            assert credit_note_id == "credit-1"
            return {"creditNumber": "GS-1"}

    class Invoice:
        def fetch_invoice_by_id(self, invoice_id: str):
            assert invoice_id == "invoice-1"
            return {"email": "customer@example.test"}

    class Wix:
        def resolve_order_summary(self, order_reference: str):
            assert order_reference == "12345"
            return {}

    class Processing:
        def build_credit_note_mail_content(self, number: str, *, customer_name: str):
            assert number == "GS-1"
            assert customer_name == "Kunde"
            return "Gutschrift", "Text"

    services = {
        SevDeskRefundClient: Sevdesk(),
        InvoiceClient: Invoice(),
        WixOrdersClient: Wix(),
        InvoiceProcessingService: Processing(),
    }

    class BlockingContainer(_Container):
        def __init__(self) -> None:
            super().__init__(Flow(), Sevdesk())
            self.block = False
            self.resolved: list[object] = []

        def resolve(self, service_type: object) -> object:
            self.resolve_threads.append(get_ident())
            if service_type is FlowRefundsClient:
                return self.flow
            self.resolved.append(service_type)
            if self.block and not entered.is_set():
                entered.set()
                assert release.wait(2)
            return services[service_type]

    container = BlockingContainer()
    dialog = RefundsDialog(container)  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
    dialog._rows = [  # noqa: SLF001
        {
            "process_status": "done_creditnote",
            "sevdesk_credit_note_id": "credit-1",
            "sevdesk_invoice_id": "invoice-1",
            "wix_order_number": "12345",
        }
    ]
    captured: list[object] = []
    monkeypatch.setattr(dialog, "_confirm_credit_note_mail", lambda payload, _id: captured.append(payload))
    container.block = True
    dialog._send_mail(0)  # noqa: SLF001
    qtbot.waitUntil(entered.is_set, timeout=1000)
    beats: list[bool] = []
    QTimer.singleShot(20, lambda: beats.append(True))
    qtbot.waitUntil(lambda: bool(beats), timeout=1000)
    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001

    assert container.resolved == [
        SevDeskRefundClient,
        InvoiceClient,
        WixOrdersClient,
        InvoiceProcessingService,
    ]
    assert container.resolve_threads and all(thread != ui_thread for thread in container.resolve_threads)
    assert captured == [{"number": "GS-1", "email": "customer@example.test", "subject": "Gutschrift", "body": "Text"}]


def test_refund_dialog_stays_open_during_mail_write(qtbot) -> None:
    entered, release = Event(), Event()

    class Flow:
        def list_refunds(self, *, limit: int):
            del limit
            return []

    class Sevdesk:
        pass

    dialog = RefundsDialog(_Container(Flow(), Sevdesk()))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001

    def send_mail() -> str:
        entered.set()
        assert release.wait(3)
        return "customer@example.test"

    try:
        dialog._start_worker(send_mail, lambda _payload: None, blocks_close=True)  # noqa: SLF001
        qtbot.waitUntil(entered.is_set, timeout=1000)
        dialog.accept()
        dialog.reject()
        dialog.close()
        assert dialog.isVisible()

        release.set()
        qtbot.waitUntil(lambda: dialog._worker is None, timeout=2000)  # noqa: SLF001
    finally:
        release.set()

    assert dialog._write_worker is None  # noqa: SLF001
    dialog.reject()
    assert not dialog.isVisible()
