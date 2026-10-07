from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDate, Qt

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

    def list_purpose_rules(self) -> list[object]:
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
    assert "Kategorie" in headers
    assert "MusikHeroes" not in headers
    assert view.findChildren(type(view._wizard_button))
    assert {item.initials for item in view._positions} == {"XW", "MH", "WM", "BH", "PRIV"}


def test_expense_review_period_presets_fill_editable_dates(qtbot: object) -> None:
    view = ExpenseReviewView(_ContainerStub())  # type: ignore[arg-type]
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    today = datetime.now(tz=ZoneInfo("Europe/Vienna")).date()
    previous_end = today.replace(day=1) - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    months = (
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    )

    assert view._period.currentText() == f"{months[previous_start.month - 1]} {previous_start.year}"
    assert view._start.date().toPython() == previous_start
    assert view._end.date().toPython() == previous_end

    current_start = today.replace(day=1)
    view._period.setCurrentIndex(0)
    assert view._start.date().toPython() == current_start
    assert view._end.date().toPython() == (current_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    view._start.setDate(QDate(current_start.year, current_start.month, 2))
    assert view._period.currentText() == "Benutzerdefiniert"
