from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from xw_studio.services.transfers.models import (
    TransferAttachment,
    TransferCase,
    TransferFieldSource,
    TransferPaymentData,
)
from xw_studio.services.transfers.service import OffeneUeberweisungenService
from xw_studio.ui.modules.rechnungen.offene_ueberweisungen_dialog import OffeneUeberweisungenDialog


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


def test_dialog_defer_calls_service(qtbot: object, monkeypatch) -> None:
    service = _FakeTransferService()
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_dialog_loaded(qtbot, dialog)
    accepted = {"value": False}

    monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("value", True))

    dialog._note.setText("spaeter")  # noqa: SLF001
    dialog._defer()  # noqa: SLF001

    assert service.mark_deferred_calls == [("m1", "spaeter")]
    assert accepted["value"] is True


def test_dialog_mark_done_calls_service_after_confirmation(qtbot: object, monkeypatch) -> None:
    service = _FakeTransferService()
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_dialog_loaded(qtbot, dialog)

    monkeypatch.setattr(
        "xw_studio.ui.modules.rechnungen.offene_ueberweisungen_dialog.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog._note.setText("ok")  # noqa: SLF001
    dialog._mark_done()  # noqa: SLF001

    assert len(service.mark_done_calls) == 1
    case_id, payment, qr_path, note = service.mark_done_calls[0]
    assert case_id == "m1"
    assert payment.iban == "AT611904300234573201"
    assert qr_path == ""
    assert note == "ok"


def test_dialog_generate_qr_uses_manual_form_values(qtbot: object, monkeypatch) -> None:
    service = _FakeTransferService()
    dialog = OffeneUeberweisungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_dialog_loaded(qtbot, dialog)

    monkeypatch.setattr(
        "xw_studio.ui.modules.rechnungen.offene_ueberweisungen_dialog.PaymentQrDialog.exec",
        lambda self: 0,
    )

    dialog._recipient.setText("Manual Recipient")  # noqa: SLF001
    dialog._iban.setText("AT611904300234573201")  # noqa: SLF001
    dialog._bic.setText("BKAUATWW")  # noqa: SLF001
    dialog._amount.setText("999,99")  # noqa: SLF001
    dialog._remittance.setText("RE-MANUAL")  # noqa: SLF001

    dialog._generate_qr()  # noqa: SLF001

    assert service.last_generated_payment is not None
    assert service.last_generated_payment.recipient == "Manual Recipient"
    assert service.last_generated_payment.amount == Decimal("999.99")
    assert len(service.saved_manual_calls) == 1
