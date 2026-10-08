from __future__ import annotations

from datetime import date, datetime, timedelta
from threading import Event
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


class _DelayedExpenseServiceStub(_ExpenseServiceStub):
    def __init__(self) -> None:
        self.block = False
        self.started = Event()
        self.release = Event()
        self.release.set()

    def list_bank_expenses(self, **kwargs: object) -> list[object]:
        if self.block:
            self.started.set()
            self.release.wait(timeout=3)
        return []


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
    assert [view._tenant_tabs.tabText(index) for index in range(view._tenant_tabs.count())] == [
        "XeisWorks",
        "WüdaraMusi",
    ]
    assert view._tenant_tabs.objectName() == "expenseTenantTabs"
    assert view._tenant_tabs.expanding()
    assert view._tenant_tabs.minimumHeight() >= 62
    assert "QTabBar#expenseTenantTabs::tab:selected" in view._tenant_tabs.styleSheet()
    assert view._missing_refresh_button is not None
    view._set_missing_refresh_pending(True)
    assert view._missing_refresh_timer.isActive()
    assert not view._missing_refresh_button.isEnabled()
    view._set_missing_refresh_pending(False)
    assert not view._missing_refresh_timer.isActive()
    assert view._missing_refresh_button.isEnabled()
    view._tenant_tabs.setCurrentIndex(1)
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: "Konto WüdaraMusi" in view._status.text(), timeout=3000
    )
    assert view._account_label.text() == "Konto: WüdaraMusi"
    assert view._period.count() == 4
    today = datetime.now(tz=ZoneInfo("Europe/Vienna")).date()
    current_quarter = (today.month - 1) // 3 + 1
    previous_quarter = current_quarter - 1 or 4
    previous_year = today.year - 1 if current_quarter == 1 else today.year
    assert view._period.currentText() == f"Quartal {previous_quarter} / {previous_year}"
    assert view._start.date().toPython() == date(previous_year, (previous_quarter - 1) * 3 + 1, 1)
    assert view._end.date().toPython() == date(
        previous_year + 1 if previous_quarter == 4 else previous_year,
        1 if previous_quarter == 4 else previous_quarter * 3 + 1,
        1,
    ) - timedelta(days=1)
    view._start.setDate(view._start.date().addDays(1))
    assert view._period.currentText() == "Benutzerdefiniert"


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


def test_expense_review_allows_tenant_switch_while_other_tenant_loads(qtbot: object) -> None:
    container = _ContainerStub()
    container.service = _DelayedExpenseServiceStub()
    view = ExpenseReviewView(container)  # type: ignore[arg-type]
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    view.show()
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: view._status.text().startswith("0 ausgehende Zahlungen"), timeout=3000
    )

    container.service.block = True
    container.service.started.clear()
    container.service.release.clear()
    view._load(refresh=True)
    qtbot.waitUntil(container.service.started.is_set, timeout=3000)  # type: ignore[attr-defined]

    assert view._tenant_tabs.isEnabled()
    view._tenant_tabs.setCurrentIndex(1)
    assert view._tenant_key == "wuedara"
    assert view._workers["xw"].isRunning()

    container.service.release.set()
    qtbot.waitUntil(lambda: "xw" not in view._workers, timeout=3000)  # type: ignore[attr-defined]
