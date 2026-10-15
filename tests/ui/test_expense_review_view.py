from __future__ import annotations

from datetime import date, datetime, timedelta
from dataclasses import replace
from decimal import Decimal
from threading import Event
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QDate, QSize, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTabWidget
from pytestqt.qtbot import QtBot

from xw_office.services.expenses.service import (
    DEFAULT_EXPENSE_POSITIONS,
    BankExpenseRow,
    ExpenseDocumentView,
)
from xw_office.ui.modules.expense_review.view import ExpenseReviewView
from xw_office.ui.theme import apply_app_theme


class _ExpenseServiceStub:
    def list_positions(self, *, enabled_only: bool = True) -> list[object]:
        return list(DEFAULT_EXPENSE_POSITIONS)

    def list_bank_expenses(self, **kwargs: object) -> list[BankExpenseRow]:
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

    def list_bank_expenses(self, **kwargs: object) -> list[BankExpenseRow]:
        if self.block:
            self.started.set()
            self.release.wait(timeout=3)
        return []


def test_expense_review_uses_positions_and_settings_dialog(qtbot: object) -> None:
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


class _BankRowsServiceStub(_ExpenseServiceStub):
    def __init__(self) -> None:
        base = BankExpenseRow(
            transaction_id="xw-missing",
            value_date=date(2026, 9, 10),
            payee="Supplier",
            purpose="Subscription",
            amount=Decimal("-10"),
            currency="EUR",
            position_key="xw",
            supplier_url="https://example.com",
        )
        self.rows = [
            base,
            replace(base, transaction_id="mh-missing", position_key="mh"),
            replace(base, transaction_id="unassigned", position_key=""),
            replace(base, transaction_id="no-website", supplier_url=""),
            replace(base, transaction_id="unscanned", document_link_scan_complete=False),
            replace(
                base,
                transaction_id="linked",
                documents=(ExpenseDocumentView("Voucher", "1", "R-1", "https://example.com/1"),),
            ),
            replace(base, transaction_id="incoming", amount=Decimal("20")),
        ]
        self.calls: list[dict[str, object]] = []
        self.assignments: list[tuple[str, str]] = []

    def list_bank_expenses(self, **kwargs: object) -> list[BankExpenseRow]:
        self.calls.append(kwargs)
        return self.rows

    def assign_transaction_position(self, *, transaction_id: str, position_key: str) -> None:
        self.assignments.append((transaction_id, position_key))


def _loaded_view(qtbot: QtBot, tenant_index: int) -> tuple[ExpenseReviewView, _BankRowsServiceStub]:
    container = _ContainerStub()
    service = _BankRowsServiceStub()
    container.service = service
    view = ExpenseReviewView(container)  # type: ignore[arg-type]
    qtbot.addWidget(view)
    view.resize(1200, 850)
    view.show()
    qtbot.waitUntil(lambda: not view._workers and len(view._all_rows) == 7)
    if tenant_index:
        view._tenant_tabs.setCurrentIndex(tenant_index)
        qtbot.waitUntil(lambda: not view._workers and len(view._all_rows) == 7)
    return view, service


def _visible_ids(view: ExpenseReviewView) -> set[str]:
    return {str(row["__transaction_id"]) for row in view._table.source_rows_data()}


@pytest.mark.parametrize("tenant_index", [0, 1])
def test_bank_filters_combine_category_website_and_missing_document(
    qtbot: QtBot, tenant_index: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    view, service = _loaded_view(qtbot, tenant_index)
    assert _visible_ids(view) == {row.transaction_id for row in service.rows if row.amount < 0}
    assert {view._category_filter.itemData(i) for i in range(view._category_filter.count())} == {
        None, "", "xw", "mh", "wm", "bh", "priv",
    }

    view._missing_only.setChecked(True)
    qtbot.waitUntil(lambda: not view._workers)
    assert _visible_ids(view) == {"xw-missing", "mh-missing", "unassigned", "incoming"}

    view._category_filter.setCurrentIndex(view._category_filter.findData("mh"))
    assert _visible_ids(view) == {"mh-missing"}
    view._category_filter.setCurrentIndex(view._category_filter.findData(""))
    assert _visible_ids(view) == {"unassigned"}
    view._category_filter.setCurrentIndex(view._category_filter.findData("xw"))
    assert _visible_ids(view) == {"xw-missing", "incoming"}

    # A refreshed sevDesk link must immediately remove the row from the active filter.
    service.rows = [
        replace(row, documents=service.rows[5].documents)
        if row.transaction_id == "xw-missing" else row
        for row in service.rows
    ]
    assert view._missing_refresh_button is not None
    manual_refreshes: list[bool] = []
    monkeypatch.setattr(view, "_load_manual_expenses", lambda: manual_refreshes.append(True))
    QTest.mouseClick(view._missing_refresh_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not view._workers)
    assert service.calls[-1]["refresh_document_links"] is True
    assert service.calls[-1]["refresh"] is False
    assert manual_refreshes == [True]
    assert _visible_ids(view) == {"incoming"}
    assert view._category_filter.currentData() == "xw"
    assert view._missing_only.isChecked()

    view._category_filter.setCurrentIndex(view._category_filter.findData(None))
    view._assign_position("unassigned", "mh")
    view._category_filter.setCurrentIndex(view._category_filter.findData(""))
    assert not _visible_ids(view)
    qtbot.waitUntil(lambda: not view._assignment_workers)
    assert service.assignments == [("unassigned", "mh")]
    view._missing_only.setChecked(False)
    view._category_filter.setCurrentIndex(view._category_filter.findData(None))
    assert _visible_ids(view) == {row.transaction_id for row in service.rows if row.amount < 0}


@pytest.mark.parametrize("tenant_index", [0, 1])
@pytest.mark.parametrize("theme", ["dark_gold", "light_gold"])
def test_bank_toolbar_and_settings_dialog(
    qtbot: QtBot, tenant_index: int, theme: str
) -> None:
    view, _ = _loaded_view(qtbot, tenant_index)
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    original_stylesheet = application.styleSheet()
    apply_app_theme(application, theme)
    qtbot.wait(20)
    main_tabs = view.findChildren(QTabWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
    assert len(main_tabs) == 1
    assert [main_tabs[0].tabText(i) for i in range(main_tabs[0].count())] == ["Kontobewegungen"]
    assert view._missing_refresh_button is not None
    buttons = (view._add_button, view._missing_refresh_button, view._settings_button)
    for button in buttons:
        assert button.iconSize() == QSize(32, 32)
        assert button.size() == QSize(46, 46)
        assert not button.icon().isNull()
        assert "border: none" in button.styleSheet()
        assert "padding: 0px" in button.styleSheet()
        assert button.geometry().bottom() < view._table.geometry().top()
    assert buttons[0].x() < buttons[1].x() < buttons[2].x()
    assert buttons[2].geometry().right() == view._table.geometry().right()

    settings_tabs = view._settings_dialog.findChild(QTabWidget)
    assert settings_tabs is not None
    assert [settings_tabs.tabText(i) for i in range(settings_tabs.count())] == [
        "Kategorien", "Zuordnungsregeln", "Lieferantenportale", "Verwendungszwecke",
    ]
    QTimer.singleShot(0, view._settings_dialog.reject)
    QTest.mouseClick(view._settings_button, Qt.MouseButton.LeftButton)
    assert view._tenant_label in view._settings_dialog.windowTitle()
    assert view._settings_dialog.result() == QDialog.DialogCode.Rejected
    application.setStyleSheet(original_stylesheet)


def test_missing_filter_is_refreshed_after_an_inflight_cached_load(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _ContainerStub()
    service = _BankRowsServiceStub()
    container.service = service
    started, release = Event(), Event()
    original_load = service.list_bank_expenses

    def delayed_load(**kwargs: object) -> list[BankExpenseRow]:
        started.set()
        release.wait(timeout=3)
        return original_load(**kwargs)

    monkeypatch.setattr(service, "list_bank_expenses", delayed_load)
    view = ExpenseReviewView(container)  # type: ignore[arg-type]
    qtbot.addWidget(view)
    qtbot.waitUntil(started.is_set)
    view._missing_only.setChecked(True)
    release.set()
    qtbot.waitUntil(lambda: len(service.calls) == 2 and not view._workers)
    assert service.calls[0]["refresh_document_links"] is False
    assert service.calls[1]["refresh_document_links"] is True
    assert _visible_ids(view) == {"xw-missing", "mh-missing", "unassigned", "incoming"}


def test_tenant_switch_keeps_filters_and_restores_only_its_own_rows(qtbot: QtBot) -> None:
    view, service = _loaded_view(qtbot, 0)
    view._missing_only.setChecked(True)
    qtbot.waitUntil(lambda: not view._workers)
    view._category_filter.setCurrentIndex(view._category_filter.findData("xw"))
    service.rows = [replace(service.rows[0], transaction_id="wuedara-missing")]
    view._tenant_tabs.setCurrentIndex(1)
    qtbot.waitUntil(lambda: not view._workers)
    assert _visible_ids(view) == {"wuedara-missing"}
    view._tenant_tabs.setCurrentIndex(0)
    assert view._missing_only.isChecked()
    assert view._category_filter.currentData() == "xw"
    assert _visible_ids(view) == {"xw-missing", "incoming"}


def test_add_icon_still_opens_manual_expense_action(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        ExpenseReviewView, "_add_manual_expense", lambda self: opened.append(self._tenant_key)
    )
    view, _ = _loaded_view(qtbot, 0)
    QTest.mouseClick(view._add_button, Qt.MouseButton.LeftButton)
    assert opened == ["xw"]
    view._tenant_tabs.setCurrentIndex(1)
    qtbot.waitUntil(lambda: not view._workers)
    QTest.mouseClick(view._add_button, Qt.MouseButton.LeftButton)
    assert opened == ["xw", "wuedara"]
