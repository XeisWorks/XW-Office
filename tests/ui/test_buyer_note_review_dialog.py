"""The START buyer-note decision dialog must preserve its execution meaning."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QPushButton

from xw_office.services.invoice_processing.buyer_notes import (
    BUYER_NOTE_ACK, BUYER_NOTE_DELIVERY_NOTE, BUYER_NOTE_SKIP,
    BuyerNoteCase, BuyerNoteProduct, BuyerNoteSource,
)
from xw_office.ui.modules.rechnungen import buyer_note_review_dialog
from xw_office.ui.modules.rechnungen.buyer_note_review_dialog import BuyerNoteReviewDialog
from xw_office.ui.modules.rechnungen.buyer_note_delivery_dialog import BuyerNoteDeliveryDialog


class _Signal:
    def connect(self, _callback: object) -> None:
        pass


class _RunningWorker:
    def __init__(self, _job: object) -> None:
        self.job = _job
        self.running = True
        self.signals = type(
            "Signals", (), {"result": _Signal(), "error": _Signal(), "finished": _Signal()}
        )()

    def isRunning(self) -> bool:
        return self.running

    def start(self) -> None:
        pass


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


def test_actions_share_one_row_with_cancel_before_done(qtbot: object) -> None:
    dialog = BuyerNoteReviewDialog([_case("1")], allow_delivery_note=False)
    qtbot.addWidget(dialog)
    row = dialog.layout().itemAt(dialog.layout().count() - 1).layout()
    assert isinstance(row, QHBoxLayout)
    buttons = [row.itemAt(index).widget() for index in range(row.count())]
    buttons = [button for button in buttons if isinstance(button, QPushButton)]
    assert [button.text() for button in buttons] == [
        "▤ LS", "✉ MAIL", "↷ SKIP", "✕ CANCEL", "✓ ERLEDIGT",
    ]
    assert all(button.toolTip() for button in buttons)


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


def test_delivery_dialog_reject_and_window_close_wait_for_worker_without_blocking(
    qtbot: object, monkeypatch: object
) -> None:
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.buyer_note_delivery_dialog.BackgroundWorker",
        _RunningWorker,
    )
    dialog = BuyerNoteDeliveryDialog(
        _case("1"), ("Kundin", "Hauptstraße 1"), "Vorhandener Text", object()
    )
    qtbot.addWidget(dialog)
    dialog.show()

    dialog._prepare("open")  # noqa: SLF001
    dialog.reject()
    assert dialog.isVisible()
    dialog.close()
    assert dialog.isVisible()
    assert "läuft noch" in dialog._status.text()  # noqa: SLF001

    dialog._worker.running = False  # type: ignore[union-attr]  # noqa: SLF001
    dialog._on_finished()  # noqa: SLF001
    dialog.close()
    assert not dialog.isVisible()


def test_buyer_note_review_window_close_waits_for_outlook_worker(
    qtbot: object, monkeypatch: object
) -> None:
    monkeypatch.setattr(buyer_note_review_dialog, "BackgroundWorker", _RunningWorker)
    case = replace(_case("1"), customer_email="customer@example.test")
    dialog = BuyerNoteReviewDialog([case], allow_delivery_note=False, container=object())
    qtbot.addWidget(dialog)
    dialog.show()

    dialog._open_customer_mail()  # noqa: SLF001
    dialog.reject()
    assert dialog.isVisible()
    dialog.close()
    assert dialog.isVisible()

    dialog._mail_worker.running = False  # type: ignore[union-attr]  # noqa: SLF001
    dialog._mail_finished()  # noqa: SLF001
    dialog.close()
    assert not dialog.isVisible()


def test_customer_reply_puts_original_note_after_outlook_signature(
    qtbot: object, monkeypatch: object
) -> None:
    monkeypatch.setattr(buyer_note_review_dialog, "BackgroundWorker", _RunningWorker)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        buyer_note_review_dialog, "open_classic_outlook_draft",
        lambda **kwargs: calls.append(kwargs),
    )

    class _Container:
        def resolve(self, _service: object) -> object:
            return type("Secrets", (), {"get_secret": lambda _self, _name: "office@xeisworks.at"})()

    case = replace(_case("1"), customer_email="customer@example.test")
    dialog = BuyerNoteReviewDialog([case], allow_delivery_note=False, container=_Container())
    qtbot.addWidget(dialog)
    dialog._open_customer_mail()  # noqa: SLF001
    dialog._mail_worker.job()  # type: ignore[union-attr]  # noqa: SLF001

    assert calls[0]["to_email"] == "customer@example.test"
    assert "[Antwort hier eingeben]" in str(calls[0]["body"])
    assert "> Bitte prüfen" in str(calls[0]["body_after_signature"])
    assert "Ursprüngliche Käufernotiz" not in str(calls[0]["body"])
