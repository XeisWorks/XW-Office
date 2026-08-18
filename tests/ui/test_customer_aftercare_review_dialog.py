from __future__ import annotations

from xw_office.core.config import AppConfig
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.ui.modules.rechnungen.customer_aftercare_review_dialog import (
    CustomerAftercareReviewDialog,
)


def _case(**overrides: object) -> CustomerAftercareCase:
    defaults: dict[str, object] = {
        "case_type": "",
        "ai_suggested_type": "B2B_WRONG_DELIVERY",
        "ai_payload_json": '{"error_party": "xeisworks"}',
        "customer_name": "Musikhaus Mueller",
        "customer_email": "mueller@example.com",
        "source_wix_order_number": "21842",
        "courtesy": True,
        "note": "",
    }
    defaults.update(overrides)
    return CustomerAftercareCase(**defaults)


def _items() -> list[CustomerAftercareItem]:
    return [
        CustomerAftercareItem(role="WRONG_DELIVERED", name="Notenheft A", sku="XW-1", quantity=2),
        CustomerAftercareItem(role="MISSING_TO_SEND", name="Notenheft B", sku="XW-2", quantity=1),
    ]


def test_dialog_prefills_ai_suggestion_and_items(qtbot: object) -> None:
    dialog = CustomerAftercareReviewDialog(_case(), _items(), config=AppConfig())
    qtbot.addWidget(dialog)

    assert dialog._type_combo.currentData() == "B2B_WRONG_DELIVERY"  # noqa: SLF001
    assert dialog._courtesy_checkbox.isChecked() is True  # noqa: SLF001
    assert "Notenheft A" in dialog._format_items([_items()[0]])  # noqa: SLF001
    assert "Wartet auf neue Bestellung" in dialog._trigger_label.text()  # noqa: SLF001


def test_dialog_shows_immediate_trigger_for_b2c(qtbot: object) -> None:
    dialog = CustomerAftercareReviewDialog(
        _case(ai_suggested_type="B2C_WRONG_DELIVERY"), _items(), config=AppConfig()
    )
    qtbot.addWidget(dialog)

    assert dialog._trigger_label.text() == "Sofort fällig"  # noqa: SLF001
    assert dialog._due_label.text() == "—"  # noqa: SLF001


def test_dialog_shows_manual_trigger_for_unknown(qtbot: object) -> None:
    dialog = CustomerAftercareReviewDialog(
        _case(ai_suggested_type="UNKNOWN"), _items(), config=AppConfig()
    )
    qtbot.addWidget(dialog)

    assert "Manuell" in dialog._trigger_label.text()  # noqa: SLF001


def test_apply_button_produces_confirm_outcome(qtbot: object) -> None:
    dialog = CustomerAftercareReviewDialog(_case(), _items(), config=AppConfig())
    qtbot.addWidget(dialog)

    dialog._courtesy_checkbox.setChecked(False)  # noqa: SLF001
    dialog._note_edit.setPlainText("Bitte pruefen")  # noqa: SLF001
    dialog._btn_apply.click()  # noqa: SLF001

    outcome = dialog.outcome()
    assert outcome is not None
    assert outcome.action == "confirm"
    assert outcome.case_type == "B2B_WRONG_DELIVERY"
    assert outcome.courtesy is False
    assert outcome.note == "Bitte pruefen"
    assert dialog.result() == dialog.DialogCode.Accepted


def test_edit_button_produces_defer_outcome_and_rejects(qtbot: object) -> None:
    dialog = CustomerAftercareReviewDialog(_case(), _items(), config=AppConfig())
    qtbot.addWidget(dialog)

    dialog._btn_edit.click()  # noqa: SLF001

    outcome = dialog.outcome()
    assert outcome is not None
    assert outcome.action == "defer"
    assert dialog.result() == dialog.DialogCode.Rejected


def test_ignore_button_produces_ignore_outcome(qtbot: object) -> None:
    dialog = CustomerAftercareReviewDialog(_case(), _items(), config=AppConfig())
    qtbot.addWidget(dialog)

    dialog._btn_ignore.click()  # noqa: SLF001

    outcome = dialog.outcome()
    assert outcome is not None
    assert outcome.action == "ignore"
