from __future__ import annotations

from pathlib import Path

from xw_office.core.config import AppConfig, PrintingSection
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.sendungen.service import (
    OffeneSendungenService,
    SendungCase,
    SendungExtraction,
    SendungProductLine,
)
from xw_office.ui.modules.rechnungen.offene_sendungen_dialog import OffeneSendungenDialog


class _FakeSendungenService:
    def __init__(self) -> None:
        self._cases = [
            SendungCase(
                id="m1",
                received_at="2026-07-10T09:00:00Z",
                sender="kunde@example.test",
                subject="Bestellung 20868",
                snippet="Bitte senden",
                body="Versandadresse:\nMax Muster\nHauptstrasse 1\n1010 Wien\n1x Musikbuch Alpen",
                thread_id="conv-1",
                order_number="20868",
            )
        ]
        self.refresh_called = 0
        self.mark_done_calls: list[tuple[str, bool]] = []
        self.saved_manual: list[dict[str, object]] = []

    def open_count(self) -> int:
        return len(self._cases)

    def refresh_from_graph(self, *, lookback_days: int = 20, max_items: int = 150, allow_interactive_auth: bool = True) -> list[SendungCase]:
        del lookback_days, max_items, allow_interactive_auth
        self.refresh_called += 1
        return list(self._cases)

    def load_open_cases(self) -> list[SendungCase]:
        return list(self._cases)

    def extract_case_details(self, case_id: str, *, force: bool = False) -> SendungExtraction:
        del case_id, force
        return SendungExtraction(
            summary="Ein Musikbuch an Max Muster senden.",
            address_lines=["Max Muster", "Hauptstrasse 1", "1010 Wien"],
            products=[SendungProductLine(quantity="1", name="Musikbuch Alpen", sku="XW-42")],
            order_number="20868",
            source="openai",
        )

    def load_manual_fields(self, case_id: str) -> dict[str, object]:
        del case_id
        return {}

    def save_manual_fields(
        self,
        case_id: str,
        *,
        address_lines: list[str],
        products: list[SendungProductLine],
        manual_text: str = "",
    ) -> None:
        self.saved_manual.append(
            {
                "case_id": case_id,
                "address_lines": address_lines,
                "products": products,
                "manual_text": manual_text,
            }
        )

    def mark_done(self, case_id: str, *, done: bool) -> None:
        self.mark_done_calls.append((case_id, done))
        if done:
            self._cases = []

    def generate_delivery_note_pdf(self, *_args: object, **_kwargs: object) -> Path:
        return Path(__file__).resolve()


class _FakeContainer:
    config = AppConfig(printing=PrintingSection(invoice_printer="Rechnungen"))

    def __init__(self, service: _FakeSendungenService) -> None:
        self._service = service

    def resolve(self, typ: object) -> object:
        if typ is OffeneSendungenService:
            return self._service
        if typ is PrintQueueService:
            return PrintQueueService()
        raise KeyError(str(typ))


def _wait_dialog_loaded(qtbot: object, dialog: OffeneSendungenDialog) -> None:
    qtbot.waitUntil(lambda: "Max Muster" in dialog._address.toPlainText(), timeout=3000)  # noqa: SLF001


def test_dialog_constructor_does_not_refresh_graph_synchronously(qtbot: object) -> None:
    service = _FakeSendungenService()
    dialog = OffeneSendungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)

    assert service.refresh_called == 0


def test_dialog_loads_cases_and_prefills_shipping_fields(qtbot: object) -> None:
    service = _FakeSendungenService()
    dialog = OffeneSendungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_dialog_loaded(qtbot, dialog)

    assert service.refresh_called == 1
    assert dialog._status.text() == "1 offene Sendungen"  # noqa: SLF001
    assert "Ein Musikbuch" in dialog._summary.toPlainText()  # noqa: SLF001
    assert dialog._cell_text(0, 1) == "Musikbuch Alpen"  # noqa: SLF001


def test_dialog_mark_done_saves_manual_fields_and_removes_case(qtbot: object) -> None:
    service = _FakeSendungenService()
    dialog = OffeneSendungenDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_dialog_loaded(qtbot, dialog)

    dialog._manual_text.setPlainText("Bitte schnell senden")  # noqa: SLF001
    dialog._mark_done()  # noqa: SLF001

    qtbot.waitUntil(lambda: bool(service.mark_done_calls), timeout=2000)
    assert service.mark_done_calls == [("m1", True)]
    assert service.saved_manual[-1]["manual_text"] == "Bitte schnell senden"
