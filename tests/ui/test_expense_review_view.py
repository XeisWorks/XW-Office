from __future__ import annotations

from PySide6.QtCore import Qt

from xw_office.services.expenses.service import DEFAULT_EXPENSE_POSITIONS
from xw_office.ui.modules.expense_review.view import ExpenseReviewView


class _ExpenseServiceStub:
    def list_positions(self, *, enabled_only: bool = True) -> list[object]:
        return list(DEFAULT_EXPENSE_POSITIONS)

    def list_bank_expenses(self, **kwargs: object) -> list[object]:
        return []

    def list_position_rules(self) -> list[object]:
        return []

    def list_supplier_links(self) -> list[object]:
        return []


class _ContainerStub:
    def __init__(self) -> None:
        self.service = _ExpenseServiceStub()

    def resolve(self, service_type: object) -> _ExpenseServiceStub:
        return self.service


def test_expense_review_uses_positions_and_settings_tab(qtbot: object) -> None:
    view = ExpenseReviewView(_ContainerStub())  # type: ignore[arg-type]
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    view.show()

    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: view._status.text().startswith("0 ausgehende Zahlungen"), timeout=3000
    )

    headers = [
        view._table.model().headerData(column, Qt.Orientation.Horizontal)
        for column in range(view._table.model().columnCount())
    ]
    assert "Position" in headers
    assert "MusikHeroes" not in headers
    assert view.findChildren(type(view._wizard_button))
    assert {item.initials for item in view._positions} == {"XW", "MH", "WM", "BH", "PRIV"}
