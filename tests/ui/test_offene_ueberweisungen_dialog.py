from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from threading import Event

from PySide6.QtCore import QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QMessageBox

from xw_office.services.transfers.models import (
    TransferAttachment,
    TransferCase,
    TransferFieldSource,
    TransferPaymentData,
)
from xw_office.services.transfers.service import OffeneUeberweisungenService
from xw_office.core.worker import BackgroundWorker
from xw_office.ui.modules.rechnungen.offene_ueberweisungen_dialog import OffeneUeberweisungenDialog


class _FakeTransferService:
    def __init__(self) -> None:
        self._cases = [
            TransferCase(
                id="m1",
                internet_message_id="<m1@example.test>",
                conversation_id="conv-1",
                received_at="2026-07-10T10:00:00Z",
                sender="kunde@example.test",
                subject="Rechnung RE-2026-0042",
                snippet="Bitte ueberweisen",
                body="Bitte auf IBAN AT611904300234573201 zahlen.",
                thread_text="Threadtext",
            )
        ]
        self.refresh_called = 0
        self.mark_deferred_calls: list[tuple[str, str]] = []
        self.mark_done_calls: list[tuple[str, TransferPaymentData, str, str]] = []
        self.saved_manual_calls: list[tuple[str, TransferPaymentData]] = []
        self.last_generated_payment: TransferPaymentData | None = None

    def open_count(self) -> int:
        return len(self._cases)

    def refresh_from_graph(self, *, lookback_days: int = 60, max_items: int = 180, allow_interactive_auth: bool = True) -> list[TransferCase]:
        del lookback_days, max_items, allow_interactive_auth
        self.refresh_called += 1
        return list(self._cases)

    def load_open_cases(self) -> list[TransferCase]:
        return list(self._cases)

    def list_pdf_attachments(self, case_id: str) -> list[TransferAttachment]:
        del case_id
        return [TransferAttachment(id="a1", name="rechnung.pdf", content_type="application/pdf", size=123)]

    def extract_payment_data(self, case_id: str, attachment_id: str | None = None) -> TransferPaymentData:
        del case_id, attachment_id
        return TransferPaymentData(
            recipient="XeisWorks GmbH",
            iban="AT611904300234573201",
            bic="BKAUATWW",
            amount=Decimal("123.45"),
            remittance_text="RE-2026-0042",
            invoice_number="RE-2026-0042",
            source_by_field={
                "recipient": TransferFieldSource.PDF_TEXT,
                "iban": TransferFieldSource.PDF_TEXT,
                "bic": TransferFieldSource.PDF_TEXT,
                "amount": TransferFieldSource.PDF_TEXT,
                "remittance_text": TransferFieldSource.PDF_TEXT,
                "invoice_number": TransferFieldSource.PDF_TEXT,
            },
        )

    def summarize_case(self, case_id: str) -> str:
        del case_id
        return "Kurzfassung"

    def download_attachment_bytes(self, case_id: str, attachment_id: str) -> bytes:
        del case_id, attachment_id
        return b"%PDF-1.7\n%..."

    def mark_deferred(self, case_id: str, note: str = "") -> None:
        self.mark_deferred_calls.append((case_id, note))

    def mark_done_in_outlook(self, case_id: str, payment: TransferPaymentData, qr_path: str = "", note: str = "") -> None:
        self.mark_done_calls.append((case_id, payment, qr_path, note))
        self._cases = []

    def save_manual_payment(self, case_id: str, payment: TransferPaymentData) -> None:
        self.saved_manual_calls.append((case_id, payment))

    def generate_qr(self, case_id: str, payment: TransferPaymentData) -> Path:
        del case_id
        self.last_generated_payment = payment
        return Path(__file__).resolve()


class _FakeContainer:
    def __init__(self, service: _FakeTransferService) -> None:
        self._service = service

    def resolve(self, _typ: object) -> object:
        if _typ is OffeneUeberweisungenService:
            return self._service
        raise KeyError(str(_typ))


def _wait_dialog_loaded(qtbot: object, dialog: OffeneUeberweisungenDialog) -> None:
    qtbot.waitUntil(lambda: dialog._recipient.text() == "XeisWorks GmbH", timeout=3000)  # noqa: SLF001


def test_dialog_loads_case_list_and_prefills_fields(qtbot: object) -> None:
    service = _FakeTransferService()
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_dialog_loaded(qtbot, dialog)

    assert service.refresh_called == 1
    assert dialog._status.text() == "1 offene Ueberweisungen"  # noqa: SLF001
    assert dialog._recipient.text() == "XeisWorks GmbH"  # noqa: SLF001
    assert dialog._iban.text() == "AT611904300234573201"  # noqa: SLF001


def test_dialog_constructor_does_not_refresh_graph_synchronously(qtbot: object) -> None:
    service = _FakeTransferService()
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)

    assert service.refresh_called == 0


def test_service_resolution_for_initial_load_runs_off_ui_thread(qtbot: object) -> None:
    started = Event()
    release = Event()
    service = _FakeTransferService()

    class SlowContainer(_FakeContainer):
        def resolve(self, service_type: object) -> object:
            if service_type is OffeneUeberweisungenService:
                started.set()
                release.wait(2)
            return super().resolve(service_type)

    dialog = OffeneUeberweisungenDialog(SlowContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    heartbeats: list[bool] = []
    QTimer.singleShot(20, lambda: heartbeats.append(True))
    qtbot.waitUntil(started.is_set, timeout=1000)
    qtbot.waitUntil(lambda: bool(heartbeats), timeout=1000)
    assert dialog._status.text() == "Lade offene Ueberweisungen..."  # noqa: SLF001
    release.set()
    _wait_dialog_loaded(qtbot, dialog)


def test_open_count_uses_loaded_cases(qtbot: object, monkeypatch) -> None:
    service = _FakeTransferService()
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_dialog_loaded(qtbot, dialog)
    monkeypatch.setattr(service, "open_count", lambda: (_ for _ in ()).throw(AssertionError("sync read")))

    assert dialog.open_count() == 1


def test_dialog_defer_calls_service(qtbot: object, monkeypatch) -> None:
    service = _FakeTransferService()
    entered, release = Event(), Event()
    mark_deferred = service.mark_deferred

    def blocked_mark_deferred(case_id: str, note: str = "") -> None:
        entered.set()
        assert release.wait(3)
        mark_deferred(case_id, note)

    monkeypatch.setattr(service, "mark_deferred", blocked_mark_deferred)
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.show()
    _wait_dialog_loaded(qtbot, dialog)

    dialog._note.setText("spaeter")  # noqa: SLF001
    dialog._defer()  # noqa: SLF001
    qtbot.waitUntil(entered.is_set, timeout=2000)

    dialog.reject()
    dialog.close()
    assert dialog.isVisible()

    release.set()
    qtbot.waitUntil(lambda: bool(service.mark_deferred_calls), timeout=2000)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=2000)
    assert service.mark_deferred_calls == [("m1", "spaeter")]


def test_dialog_mark_done_calls_service_after_confirmation(qtbot: object, monkeypatch) -> None:
    service = _FakeTransferService()
    entered, release = Event(), Event()
    mark_done = service.mark_done_in_outlook

    def blocked_mark_done(
        case_id: str,
        payment: TransferPaymentData,
        qr_path: str = "",
        note: str = "",
    ) -> None:
        entered.set()
        assert release.wait(3)
        mark_done(case_id, payment, qr_path, note)

    monkeypatch.setattr(service, "mark_done_in_outlook", blocked_mark_done)
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.show()
    _wait_dialog_loaded(qtbot, dialog)

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.offene_ueberweisungen_dialog.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog._note.setText("ok")  # noqa: SLF001
    dialog._mark_done()  # noqa: SLF001

    qtbot.waitUntil(entered.is_set, timeout=2000)
    dialog.accept()
    dialog.reject()
    dialog.close()
    assert dialog.isVisible()

    release.set()
    qtbot.waitUntil(lambda: bool(service.mark_done_calls), timeout=2000)
    assert len(service.mark_done_calls) == 1
    case_id, payment, qr_path, note = service.mark_done_calls[0]
    assert case_id == "m1"
    assert payment.iban == "AT611904300234573201"
    assert qr_path == ""
    assert note == "ok"
    qtbot.waitUntil(lambda: dialog._action_worker is None, timeout=2000)  # noqa: SLF001
    dialog.reject()
    assert not dialog.isVisible()


def test_dialog_generate_qr_uses_manual_form_values(qtbot: object, monkeypatch) -> None:
    service = _FakeTransferService()
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_dialog_loaded(qtbot, dialog)

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.offene_ueberweisungen_dialog.PaymentQrDialog.exec",
        lambda self: 0,
    )

    dialog._recipient.setText("Manual Recipient")  # noqa: SLF001
    dialog._iban.setText("AT611904300234573201")  # noqa: SLF001
    dialog._bic.setText("BKAUATWW")  # noqa: SLF001
    dialog._amount.setText("999,99")  # noqa: SLF001
    dialog._remittance.setText("RE-MANUAL")  # noqa: SLF001

    dialog._generate_qr()  # noqa: SLF001

    qtbot.waitUntil(lambda: service.last_generated_payment is not None, timeout=2000)
    assert service.last_generated_payment is not None
    assert service.last_generated_payment.recipient == "Manual Recipient"
    assert service.last_generated_payment.amount == Decimal("999.99")
    assert len(service.saved_manual_calls) == 1


def test_dialog_close_does_not_wait_for_running_worker(qtbot: object, monkeypatch) -> None:
    dialog = OffeneUeberweisungenDialog(_FakeContainer(_FakeTransferService()))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    release = Event()
    worker = BackgroundWorker(lambda: release.wait(2))
    dialog._action_worker = worker  # noqa: SLF001
    wait_calls: list[bool] = []
    monkeypatch.setattr(BackgroundWorker, "wait", lambda *_args: wait_calls.append(True))
    worker.start()

    dialog.close()

    assert dialog._closing is True  # noqa: SLF001
    assert wait_calls == []
    release.set()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=2000)


def test_show_invoice_download_does_not_block_event_loop(qtbot: object, monkeypatch) -> None:
    service = _FakeTransferService()
    entered, release = Event(), Event()
    opened: list[str] = []

    def blocked_download(case_id: str, attachment_id: str) -> bytes:
        assert (case_id, attachment_id) == ("m1", "a1")
        entered.set()
        assert release.wait(3)
        return b"%PDF-1.7 test"

    monkeypatch.setattr(service, "download_attachment_bytes", blocked_download)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    try:
        _wait_dialog_loaded(qtbot, dialog)
        dialog._show_invoice()  # noqa: SLF001
        qtbot.waitUntil(entered.is_set)
        beats: list[bool] = []
        QTimer.singleShot(20, lambda: beats.append(True))
        qtbot.waitUntil(lambda: bool(beats))
        assert not dialog._btn_show_invoice.isEnabled()  # noqa: SLF001
    finally:
        release.set()
        qtbot.waitUntil(lambda: dialog._action_worker is None, timeout=3000)  # noqa: SLF001
    assert len(opened) == 1
    assert Path(opened[0]).read_bytes() == b"%PDF-1.7 test"
