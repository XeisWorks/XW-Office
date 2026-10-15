from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from threading import Event
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDate, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLabel
from pytestqt.qtbot import QtBot

from tests.ui.test_expense_review_view import _BankRowsServiceStub, _ContainerStub
from tests.unit.test_wuedara_expense_sources import capture
from xw_office.core.config import AppConfig
from xw_office.services.commission.service import format_euro_amount
from xw_office.services.expenses.service import (
    DEFAULT_EXPENSE_POSITIONS, BankExpenseRow, ExpenseDocumentView,
)
from xw_office.services.expenses.xw_flow_expense_client import FlowExpense, XwFlowExpenseClient
from xw_office.services.secrets.service import SecretService
from xw_office.ui.modules.expense_review.manual_expense_dialog import ManualExpenseDialog
from xw_office.ui.modules.expense_review.view import ExpenseReviewView, _DocumentDelegate


class _SharedService(_BankRowsServiceStub):
    def __init__(self) -> None:
        super().__init__()
        self.shared = [
            replace(
                self.rows[0], transaction_id="wm-bank", position_key="wm",
                documents=(ExpenseDocumentView("Voucher", "V-WM", "WM-1", "https://example.com/xw/wm"),),
            )
        ]

    def list_wuedara_shared_bank_expenses(
        self, *, start: date, end: date
    ) -> list[BankExpenseRow]:
        return [
            row for row in self.shared
            if start <= row.value_date <= end and row.position_key == "wm"
        ]


def _shared_view(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> tuple[ExpenseReviewView, _SharedService, list[FlowExpense]]:
    container = _ContainerStub()
    service = _SharedService()
    container.service = service
    monkeypatch.setattr(container, "config", AppConfig(), raising=False)
    client = XwFlowExpenseClient(AppConfig(), MagicMock(spec=SecretService))
    expenses = [
        capture("native", tenant="wuedara", category="old-category"),
        capture("wm-manual"),
        capture("xw-other", category="mh"),
    ]

    def fetch(*, tenant_key: str, start: date, end: date, active_only: bool) -> list[FlowExpense]:
        return [
            item for item in expenses if item.tenant_key == tenant_key
            and item.expense_date is not None
            and start <= date.fromisoformat(item.expense_date) <= end
        ]

    monkeypatch.setattr(client, "fetch", fetch)
    monkeypatch.setattr(client, "sync_categories", lambda **kwargs: None)
    monkeypatch.setattr(ExpenseReviewView, "flow_expense_client", property(lambda self: client))
    view = ExpenseReviewView(container)  # type: ignore[arg-type]
    qtbot.addWidget(view)
    view.resize(1400, 850)
    view.show()
    qtbot.waitUntil(lambda: bool(view._tenant_loads) and not view._workers and not view._manual_workers)
    view._start.setDate(QDate(2026, 9, 1))
    view._end.setDate(QDate(2026, 9, 30))
    qtbot.waitUntil(
        lambda: not view._workers and not view._manual_workers
        and not view._period_reload_timer.isActive()
        and view._tenant_loads["xw"][2] == (date(2026, 9, 1), date(2026, 9, 30))
    )
    return view, service, expenses


def _switch_to_wuedara(qtbot: QtBot, view: ExpenseReviewView) -> None:
    view._tenant_tabs.setCurrentIndex(1)
    view._start.setDate(QDate(2026, 9, 1))
    view._end.setDate(QDate(2026, 9, 30))
    qtbot.waitUntil(
        lambda: view._tenant_loads.get("wuedara", (None, None, None))[2]
        == (date(2026, 9, 1), date(2026, 9, 30))
        and not view._workers and not view._manual_workers
        and not view._period_reload_timer.isActive()
    )


def test_wuedara_has_no_categories_and_hidden_xw_filters_do_not_apply(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    view, _, _ = _shared_view(qtbot, monkeypatch)
    view._category_filter.setCurrentIndex(view._category_filter.findData("mh"))
    view._unassigned_only.setChecked(True)
    _switch_to_wuedara(qtbot, view)
    assert view._category_label.isHidden()
    assert view._category_filter.isHidden()
    assert view._unassigned_only.isHidden()
    assert view._table.isColumnHidden(4)
    assert view._manual_table.isColumnHidden(6)
    assert not view._missing_only.isHidden()
    assert view._table.model().rowCount() == 6
    assert not view._settings_tabs.isTabVisible(0)
    assert not view._settings_tabs.isTabVisible(1)

    view._tenant_tabs.setCurrentIndex(0)
    qtbot.waitUntil(lambda: not view._workers and not view._manual_workers)
    assert not view._category_filter.isHidden()
    assert not view._unassigned_only.isHidden()
    assert not view._table.isColumnHidden(4)
    assert not view._manual_table.isColumnHidden(6)
    assert view._category_filter.currentData() == "mh"
    assert view._unassigned_only.isChecked()
    assert view._settings_tabs.isTabVisible(0) and view._settings_tabs.isTabVisible(1)


def test_additional_expenses_merge_sources_keep_links_and_remove_reclassified_items(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    view, service, expenses = _shared_view(qtbot, monkeypatch)
    _switch_to_wuedara(qtbot, view)
    rows = view._manual_table.source_rows_data()
    assert {row["__transaction_id"] for row in rows} == {
        "manual:native", "manual:wm-manual", "xw-bank:wm-bank",
    }
    assert {row["Herkunft"] for row in rows} == {
        "WüdaraMusi · manuell", "XeisWorks · manuell", "XeisWorks · Konto",
    }
    assert all(not row.get("__positions") for row in rows)
    bank = next(row for row in rows if row["Herkunft"] == "XeisWorks · Konto")
    manual = next(row for row in rows if row["__transaction_id"] == "manual:wm-manual")
    assert bank["Betrag"] == format_euro_amount(Decimal("10"))
    assert manual["Betrag"] == format_euro_amount(Decimal("23.10"))
    assert bank["__documents"][0]["url"] == "https://example.com/xw/wm"
    assert manual["__manual_attachment_ids"] == ["wm-manual-attachment"]
    assert view._manual_table.itemDelegateForColumn(7) is view._document_delegate
    assert "XeisWorks" in view._manual_heading.text()

    view._refresh_receipts_and_manual_expenses()
    qtbot.waitUntil(lambda: not view._workers and not view._manual_workers)
    assert len(view._manual_table.source_rows_data()) == 3
    service.shared = [replace(service.shared[0], position_key="mh")]
    expenses[1] = replace(expenses[1], category_key="mh")
    view._load_cached_then_sync()
    qtbot.waitUntil(lambda: not view._workers and not view._manual_workers)
    assert [
        row["__transaction_id"] for row in view._manual_table.source_rows_data()
    ] == ["manual:native"]

    view._tenant_tabs.setCurrentIndex(0)
    qtbot.waitUntil(lambda: not view._workers and not view._manual_workers)
    assert all(
        row["__source_tenant"] == "xw" for row in view._manual_table.source_rows_data()
    )
    assert all(
        not row["__transaction_id"].startswith("xw-bank:")
        for row in view._manual_table.source_rows_data()
    )


def test_shared_expenses_follow_wuedara_period(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    view, _, _ = _shared_view(qtbot, monkeypatch)
    _switch_to_wuedara(qtbot, view)
    assert len(view._manual_table.source_rows_data()) == 3
    view._start.setDate(QDate(2026, 10, 1))
    view._end.setDate(QDate(2026, 10, 31))
    qtbot.waitUntil(
        lambda: not view._workers and not view._manual_workers
        and not view._period_reload_timer.isActive()
        and view._tenant_loads["wuedara"][2] == (date(2026, 10, 1), date(2026, 10, 31))
    )
    assert not view._manual_table.source_rows_data()


def test_shared_bank_rows_load_without_manual_bridge_configuration(
    qtbot: QtBot,
) -> None:
    container = _ContainerStub()
    container.service = _SharedService()
    view = ExpenseReviewView(container)  # type: ignore[arg-type]
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(lambda: bool(view._tenant_loads) and not view._workers)
    _switch_to_wuedara(qtbot, view)
    assert [
        row["__transaction_id"] for row in view._manual_table.source_rows_data()
    ] == ["xw-bank:wm-bank"]


@pytest.mark.parametrize("tenant", ["xw", "wuedara"])
def test_manual_dialog_only_xw_requires_category(
    qtbot: QtBot, tenant: str
) -> None:
    client = MagicMock(spec=XwFlowExpenseClient)
    dialog = ManualExpenseDialog(
        client, tenant, list(DEFAULT_EXPENSE_POSITIONS) if tenant == "xw" else [],
    )
    qtbot.addWidget(dialog)
    dialog.show()
    category_labels = [
        label for label in dialog.findChildren(QLabel) if label.text() == "Kategorie"
    ]
    assert bool(category_labels) == (tenant == "xw")
    assert dialog.category.isHidden() == (tenant == "wuedara")
    dialog.amount.setText("23,10")
    dialog.recipient.setText("Supplier")
    dialog.purpose.setText("WM-Ausgabe")
    if tenant == "xw":
        dialog.category.setCurrentIndex(1)
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    kwargs = client.create.call_args.kwargs
    assert kwargs["tenant_key"] == tenant
    assert kwargs["category_key"] == ("mh" if tenant == "xw" else "wm")
    assert kwargs["amount"] == Decimal("23.10")


def test_additional_document_icons_open_original_xw_links_and_attachments(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    view, _, _ = _shared_view(qtbot, monkeypatch)
    _switch_to_wuedara(qtbot, view)
    view._manual_table.sortByColumn(10, Qt.SortOrder.AscendingOrder)
    opened: list[str] = []
    attached: list[object] = []
    view._document_delegate.url_clicked.disconnect()
    view._document_delegate.url_clicked.connect(opened.append)
    view._document_delegate.attachment_requested.disconnect()
    view._document_delegate.attachment_requested.connect(attached.append)
    model = view._manual_table.model()
    for row in range(model.rowCount()):
        index = model.index(row, 7)
        view._manual_table.scrollTo(index)
        qtbot.wait(10)
        data = index.data(Qt.ItemDataRole.UserRole)
        if data["__transaction_id"] not in {"xw-bank:wm-bank", "manual:wm-manual"}:
            continue
        icons = _DocumentDelegate._icon_rects(view._manual_table.visualRect(index), data)
        for rect, kind, _ in icons:
            if kind in {"sevdesk", "attachment"}:
                QTest.mouseClick(
                    view._manual_table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center(),
                )
    assert opened == ["https://example.com/xw/wm"]
    assert len(attached) == 1
    assert isinstance(attached[0], dict) and attached[0]["__manual_id"] == "wm-manual"
    assert not _DocumentDelegate._icon_rects(QRect(0, 0, 100, 32), {
        "__read_only": True,
    })


@pytest.mark.parametrize("manual", [False, True])
def test_wm_assignment_finishing_after_switch_updates_wuedara_sources(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, manual: bool
) -> None:
    view, service, expenses = _shared_view(qtbot, monkeypatch)
    service.shared = []
    started, release = Event(), Event()
    if manual:
        client = view.flow_expense_client

        def update_category(
            *, expense_id: str, version: int, category_key: str, category_label: str
        ) -> FlowExpense:
            started.set()
            release.wait(timeout=3)
            expenses[2] = replace(expenses[2], category_key=category_key)
            return expenses[2]

        monkeypatch.setattr(client, "update_category", update_category)
    else:
        def assign(*, transaction_id: str, position_key: str) -> None:
            started.set()
            release.wait(timeout=3)
            service.shared = [replace(
                service.rows[0], transaction_id=transaction_id, position_key=position_key
            )]

        monkeypatch.setattr(service, "assign_transaction_position", assign)
    view._assign_position("manual:xw-other" if manual else "xw-missing", "wm")
    qtbot.waitUntil(started.is_set)
    try:
        _switch_to_wuedara(qtbot, view)
    finally:
        release.set()
    expected = "manual:xw-other" if manual else "xw-bank:xw-missing"
    qtbot.waitUntil(
        lambda: not view._assignment_workers and not view._workers and not view._manual_workers
        and expected in {
            row["__transaction_id"] for row in view._manual_table.source_rows_data()
        }
    )
    assert not view._source_reload_pending
