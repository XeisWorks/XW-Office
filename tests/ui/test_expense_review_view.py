from __future__ import annotations

from datetime import date, datetime, timedelta
from dataclasses import replace
from decimal import Decimal
from threading import Event
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QDate, QSize, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QTabWidget
from pytestqt.qtbot import QtBot
from shiboken6 import isValid

from xw_office.services.expenses.service import (
    DEFAULT_EXPENSE_POSITIONS,
    BankExpenseLoad,
    BankExpenseRow,
    ExpenseDocumentView,
    ExpensePositionView,
)
from xw_office.ui.modules.expense_review.view import ExpenseReviewView, _PurposeRuleDialog
from xw_office.ui.theme import apply_app_theme


class _ExpenseServiceStub:
    def list_positions(self, *, enabled_only: bool = True) -> list[ExpensePositionView]:
        return list(DEFAULT_EXPENSE_POSITIONS)

    def list_bank_expenses(self, **kwargs: object) -> list[BankExpenseRow]:
        return []

    def synchronize_bank_expenses(
        self, *, start: date, end: date, force: bool = False
    ) -> BankExpenseLoad:
        return BankExpenseLoad(
            self.list_bank_expenses(
                start=start, end=end, refresh=True, refresh_document_links=True, force=force
            ),
            document_scan_complete=True,
            refreshed=True,
        )

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
        lambda: view._status.text().startswith("0 ausgehende Zahlungen") and not view._workers,
        timeout=3000,
    )

    headers = [
        view._table.model().headerData(column, Qt.Orientation.Horizontal)
        for column in range(view._table.model().columnCount())
    ]
    assert "Kategorie" in headers
    assert "MusikHeroes" not in headers
    assert view._unassigned_only.text() == "Nur offene Zuordnungen anzeigen"
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
        lambda: "Konto WüdaraMusi" in view._status.toolTip() and not view._workers,
        timeout=3000,
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
        lambda: view._status.text().startswith("0 ausgehende Zahlungen") and not view._workers,
        timeout=3000,
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
    qtbot.waitUntil(lambda: not view._workers, timeout=3000)  # type: ignore[attr-defined]


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
    view.resize(1400, 850)
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
    assert service.calls[-1]["refresh"] is True
    assert service.calls[-1]["force"] is True
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
    assert not main_tabs
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
    assert service.calls[0]["refresh"] is False
    assert service.calls[1]["refresh_document_links"] is True
    assert service.calls[1]["force"] is False
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


@pytest.mark.parametrize("tenant_index", [0, 1])
def test_unassigned_filter_combines_and_updates_after_assignment(
    qtbot: QtBot, tenant_index: int
) -> None:
    view, _ = _loaded_view(qtbot, tenant_index)
    view._unassigned_only.setChecked(True)
    assert _visible_ids(view) == {"unassigned"}
    view._missing_only.setChecked(True)
    assert _visible_ids(view) == {"unassigned"}
    view._category_filter.setCurrentIndex(view._category_filter.findData("mh"))
    assert not _visible_ids(view)
    view._category_filter.setCurrentIndex(view._category_filter.findData(None))
    view._assign_position("unassigned", "mh")
    assert not _visible_ids(view)
    qtbot.waitUntil(lambda: not view._assignment_workers)


@pytest.mark.parametrize("theme", ["dark_gold", "light_gold"])
def test_main_table_gets_space_and_manual_table_shows_only_two_rows(
    qtbot: QtBot, theme: str
) -> None:
    view, _ = _loaded_view(qtbot, 0)
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    original_stylesheet = application.styleSheet()
    try:
        apply_app_theme(application, theme)
        view._manual_table.set_data([{"Empfänger": f"Supplier {index}"} for index in range(6)])
        qtbot.wait(30)
        height = view._manual_table.verticalHeader().defaultSectionSize()
        assert view._manual_table.viewport().height() <= 2 * height
        assert view._manual_table.verticalScrollBar().maximum() > 0
        assert view._table.height() > 4 * view._manual_table.height()
        assert view._status.parentWidget() is view._unassigned_only.parentWidget()
        assert view._status.x() > view._unassigned_only.geometry().right()
        assert view._status.text() == "6 ausgehende Zahlungen"
        button_labels = [button.text().lower() for button in view.findChildren(QPushButton)]
        assert not any("belege neu prüfen" in text for text in button_labels)
        assert not any("offene zuordnungen prüfen" in text for text in button_labels)
        assert not any("zweck für empfänger bereinigen" in text for text in button_labels)
    finally:
        application.setStyleSheet(original_stylesheet)


def test_cached_rows_remain_visible_until_background_sync_finishes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _ContainerStub()
    service = _BankRowsServiceStub()
    container.service = service
    started, release = Event(), Event()

    def delayed_sync(*, start: date, end: date, force: bool = False) -> BankExpenseLoad:
        started.set()
        release.wait(timeout=3)
        return BankExpenseLoad(
            [replace(service.rows[0], transaction_id="updated")],
            document_scan_complete=True, refreshed=True,
        )

    monkeypatch.setattr(service, "synchronize_bank_expenses", delayed_sync)
    view = ExpenseReviewView(container)  # type: ignore[arg-type]
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(started.is_set)
    try:
        assert "xw-missing" in _visible_ids(view)
        assert "Hintergrund" in view._sync_status.text()
        assert view._missing_refresh_button is not None
        assert not view._missing_refresh_button.isEnabled()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not view._workers)
    assert _visible_ids(view) == {"updated"}
    assert view._missing_refresh_button.isEnabled()


def test_failed_background_sync_preserves_rows_without_retry_loop(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def fail_sync(*args: object, **kwargs: object) -> BankExpenseLoad:
        calls.append(True)
        raise RuntimeError("sevDesk unavailable")

    monkeypatch.setattr(_BankRowsServiceStub, "synchronize_bank_expenses", fail_sync)
    view, _ = _loaded_view(qtbot, 0)
    assert "xw-missing" in _visible_ids(view)
    assert "fehlgeschlagen" in view._sync_status.text()
    assert "sevDesk unavailable" in view._sync_status.text()
    qtbot.wait(100)
    assert calls == [True]


@pytest.mark.parametrize("tenant_index", [0, 1])
def test_purpose_cleanup_opens_only_on_purpose_column_double_click(
    qtbot: QtBot, tenant_index: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    view, service = _loaded_view(qtbot, tenant_index)
    saved: list[dict[str, str]] = []
    opened: list[str] = []

    def accept_rule(dialog: _PurposeRuleDialog) -> int:
        opened.append(dialog.payee.text())
        dialog.remove_text.setText("Subscription")
        return QDialog.DialogCode.Accepted

    def save_rule(**kwargs: str) -> None:
        saved.append(kwargs)

    monkeypatch.setattr(_PurposeRuleDialog, "exec", accept_rule)
    monkeypatch.setattr(service, "add_purpose_rule", save_rule, raising=False)
    view._table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    other_column = view._table.model().index(0, 1)
    QTest.mouseDClick(
        view._table.viewport(), Qt.MouseButton.LeftButton,
        pos=view._table.visualRect(other_column).center(),
    )
    assert not opened
    purpose_column = view._table.model().index(0, 2)
    QTest.mouseClick(
        view._table.viewport(), Qt.MouseButton.LeftButton,
        pos=view._table.visualRect(purpose_column).center(),
    )
    QTest.mouseDClick(
        view._table.viewport(), Qt.MouseButton.LeftButton,
        pos=view._table.visualRect(purpose_column).center(),
    )
    qtbot.waitUntil(lambda: bool(saved) and not view._workers)
    assert opened == ["Supplier"]
    assert saved == [{"payee": "Supplier", "remove_text": "Subscription", "label": "Supplier"}]


def test_period_change_loads_cache_before_refreshing_new_period(qtbot: QtBot) -> None:
    view, service = _loaded_view(qtbot, 0)
    previous_calls = len(service.calls)
    view._period.setCurrentIndex(0)
    qtbot.waitUntil(
        lambda: len(service.calls) == previous_calls + 2
        and not view._workers and not view._period_reload_timer.isActive()
    )
    cached, refreshed = service.calls[-2:]
    assert cached["refresh"] is False
    assert refreshed["refresh"] is True and refreshed["force"] is False
    assert cached["start"] == view._start.date().toPython()
    assert refreshed["end"] == view._end.date().toPython()


def test_background_sync_can_finish_after_view_is_destroyed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _ContainerStub()
    service = _BankRowsServiceStub()
    container.service = service
    view = ExpenseReviewView(container)  # type: ignore[arg-type]
    view.show()
    qtbot.waitUntil(lambda: not view._workers and len(view._all_rows) == 7)
    started, release = Event(), Event()

    def delayed_sync(*args: object, **kwargs: object) -> BankExpenseLoad:
        started.set()
        release.wait(timeout=3)
        return BankExpenseLoad(service.rows, document_scan_complete=True)

    monkeypatch.setattr(service, "synchronize_bank_expenses", delayed_sync)
    view._load(refresh=True)
    qtbot.waitUntil(started.is_set)
    view.deleteLater()
    qtbot.waitUntil(lambda: not isValid(view))
    release.set()
    qtbot.waitUntil(lambda: not view._workers)


def test_reopening_view_reads_cache_and_checks_freshness(qtbot: QtBot) -> None:
    view, service = _loaded_view(qtbot, 0)
    previous_calls = len(service.calls)
    view.hide()
    view.show()
    qtbot.waitUntil(lambda: len(service.calls) == previous_calls + 2 and not view._workers)
    assert service.calls[-2]["refresh"] is False
    assert service.calls[-1]["force"] is False


def test_period_change_discards_stale_manual_expenses_and_reloads_current_period(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = Event(), Event()
    fetched: list[tuple[date, date]] = []
    applied: list[tuple[date, date]] = []

    class _ManualClient:
        def sync_categories(self, **kwargs: object) -> None:
            pass

        def fetch(
            self, *, tenant_key: str, start: date, end: date, active_only: bool
        ) -> list[object]:
            fetched.append((start, end))
            if len(fetched) == 1:
                started.set()
                release.wait(timeout=3)
            return []

    client = _ManualClient()
    monkeypatch.setattr(ExpenseReviewView, "flow_expense_client", property(lambda self: client))
    original_apply = ExpenseReviewView._on_manual_loaded

    def apply(self: ExpenseReviewView, tenant_key: str, payload: object) -> None:
        applied.append(self._selected_period())
        original_apply(self, tenant_key, payload)

    monkeypatch.setattr(ExpenseReviewView, "_on_manual_loaded", apply)
    container = _ContainerStub()
    monkeypatch.setattr(container, "config", object(), raising=False)
    view = ExpenseReviewView(container)  # type: ignore[arg-type]
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(started.is_set)
    try:
        view._period.setCurrentIndex(0)
        qtbot.waitUntil(
            lambda: not view._workers
            and view._tenant_loads["xw"][2] == view._selected_period()
        )
    finally:
        release.set()
    qtbot.waitUntil(lambda: len(fetched) == 2 and not view._manual_workers)
    assert fetched[0] != fetched[1]
    assert fetched[1] == view._selected_period()
    assert applied == [view._selected_period()]
