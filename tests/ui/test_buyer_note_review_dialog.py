"""The START buyer-note decision dialog must preserve its execution meaning."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QPlainTextEdit

from xw_office.services.invoice_processing.buyer_notes import (
    BUYER_NOTE_ACK, BUYER_NOTE_DELIVERY_NOTE, BUYER_NOTE_SKIP,
    BuyerNoteCase, BuyerNoteProduct, BuyerNoteSource,
)
from xw_office.ui.modules.rechnungen import buyer_note_review_dialog
from xw_office.ui.modules.rechnungen.buyer_note_review_dialog import BuyerNoteReviewDialog
from xw_office.ui.modules.rechnungen.buyer_note_delivery_dialog import BuyerNoteDeliveryDialog


def _case(invoice_id: str) -> BuyerNoteCase:
    return BuyerNoteCase(
        invoice_id=invoice_id, invoice_number=f"RE-{invoice_id}", order_reference=invoice_id,
        customer_name="Kundin", sources=(BuyerNoteSource("wix_order", "Wix", "Bitte prüfen"),),
        physical_delivery=True, address_lines=("Kundin", "Hauptstraße 1"),
        products=(BuyerNoteProduct("2", "Trompete", "XW-1"),),
    )


def test_acknowledge_and_skip_complete_start_review(qtbot: object) -> None:
    dialog = BuyerNoteReviewDialog([_case("1"), _case("2")], allow_delivery_note=False)
    qtbot.addWidget(dialog)
    assert dialog._products.count() == 1  # noqa: SLF001
    assert dialog._products.item(0).text() == "2 × Trompete · XW-1"  # noqa: SLF001
    assert "Bitte prüfen" in dialog._note.toPlainText()  # noqa: SLF001
    dialog._ack.click()  # noqa: SLF001
    assert dialog._case_list.currentRow() == 1  # noqa: SLF001
    dialog._skip.click()  # noqa: SLF001
    assert dialog.result() == QDialog.DialogCode.Accepted
    selections = dialog.selections()
    assert selections["1"][1].action == BUYER_NOTE_ACK
    assert selections["2"][1].action == BUYER_NOTE_SKIP


def test_cancel_rejects_without_start_decision(qtbot: object) -> None:
    dialog = BuyerNoteReviewDialog([_case("1")], allow_delivery_note=False)
    qtbot.addWidget(dialog)
    dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.selections() == {}


def test_delivery_preview_can_schedule_without_printing(qtbot: object) -> None:
    dialog = BuyerNoteDeliveryDialog(_case("1"), ("Kundin", "Hauptstraße 1"), "Geprüft", object())
    qtbot.addWidget(dialog)
    assert any("2 × Trompete" in editor.toPlainText()
               for editor in dialog.findChildren(QPlainTextEdit))
    dialog._schedule.click()  # noqa: SLF001
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.output == "schedule"
    assert dialog.manual_note == "Geprüft"


def test_scheduled_delivery_note_is_passed_to_start(qtbot: object, monkeypatch: object) -> None:
    class _Preview:
        output = "schedule"
        manual_note = "Geprüfter Hinweis"

        def __init__(self, *_args: object) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(buyer_note_review_dialog, "BuyerNoteDeliveryDialog", _Preview)  # type: ignore[attr-defined]
    dialog = BuyerNoteReviewDialog([_case("1")], allow_delivery_note=True, container=object())
    qtbot.addWidget(dialog)
    dialog._delivery.click()  # noqa: SLF001
    selection = dialog.selections()["1"][1]
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert selection.action == BUYER_NOTE_DELIVERY_NOTE
    assert selection.manual_note == "Geprüfter Hinweis"
