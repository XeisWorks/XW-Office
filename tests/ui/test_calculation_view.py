"""Focused layout tests for the commission workspace."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtWidgets import QApplication

from xw_office.services.calculation.service import CalculationService
from xw_office.services.commission.service import (
    CategoryBreakdownRow,
    CommissionPeriod,
    CommissionProfile,
    CommissionRunResult,
    CommissionService,
    CommissionSummary,
)
from xw_office.services.expenses.service import BankExpenseRow
from xw_office.ui.modules.calculation.view import CalculationView


class _CommissionServiceStub:
    def __init__(self) -> None:
        self.profile = CommissionProfile(
            key="musikheroes",
            label="MusikHeroes",
            category_names=("MusikHeroes",),
        )

    def list_profiles(self) -> list[CommissionProfile]:
        return [self.profile]

    def get_profile(self, _key: str) -> CommissionProfile:
        return self.profile


class _CalculationServiceStub:
    def load_articles(self) -> list[object]:
        return []


class _ContainerStub:
    def __init__(self) -> None:
        self.commission = _CommissionServiceStub()
        self.calculation = _CalculationServiceStub()

    def resolve(self, service_type: type[object]) -> object:
        if service_type is CommissionService:
            return self.commission
        if service_type is CalculationService:
            return self.calculation
        raise KeyError(service_type)


def test_commission_view_uses_compact_tables_and_collapsed_documents(qtbot: object) -> None:
    view = CalculationView(_ContainerStub())  # type: ignore[arg-type]
    qtbot.addWidget(view)

    assert view._product_table._model._columns == ["SKU", "Name", "Verkauft", "Netto"]  # noqa: SLF001
    assert view._category_table._model._columns == [  # noqa: SLF001
        "Kategorie",
        "Menge",
        "Netto",
        "Brutto",
    ]
    assert not view._documents_group.isChecked()  # noqa: SLF001
    assert view._doc_table.isHidden()  # noqa: SLF001
    assert view._embedded_expenses_table.height() == view._table_height_for_rows(  # noqa: SLF001
        view._embedded_expenses_table, row_count=5  # noqa: SLF001
    )


def test_commission_overview_uses_profile_category_order_and_plain_clipboard_numbers(
    qtbot: object,
) -> None:
    view = CalculationView(_ContainerStub())  # type: ignore[arg-type]
    qtbot.addWidget(view)
    profile = view._commission_service.get_profile("musikheroes")  # noqa: SLF001
    profile = CommissionProfile(
        key=profile.key,
        label=profile.label,
        category_names=("MusikHeroes", "MusikHeroes_Noten digital"),
    )
    result = CommissionRunResult(
        profile=profile,
        period=CommissionPeriod(date(2026, 11, 1), date(2026, 11, 30), "month", date(2026, 11, 5)),
        summary=CommissionSummary(),
        product_rows=[],
        category_rows=[
            CategoryBreakdownRow("MusikHeroes_Noten digital", quantity=2, net_amount=10.5),
            CategoryBreakdownRow("MusikHeroes", quantity=1234, net_amount=1234.5),
        ],
        document_rows=[],
        anomalies=[],
        source_stats={},
    )

    view._populate_category_table(result)  # noqa: SLF001

    rows = view._category_table.source_rows_data()  # noqa: SLF001
    assert [row["Kategorie"] for row in rows] == ["MusikHeroes", "MusikHeroes_Noten digital"]
    assert rows[0]["__clipboard__Netto"] == "1234,5"
    assert view._clipboard_number(Decimal("10.00")) == "10"  # noqa: SLF001
    displayed_rows = [
        view._category_table.model().index(row, 0).data()  # noqa: SLF001
        for row in range(view._category_table.model().rowCount())  # noqa: SLF001
    ]
    assert displayed_rows == ["MusikHeroes", "MusikHeroes_Noten digital"]

    view._copy_overview_cell(view._category_table.model().index(0, 2))  # noqa: SLF001

    assert QApplication.clipboard().text() == "1234,5"
    assert view._copy_notice is not None  # noqa: SLF001
    assert "background" in view._copy_notice.styleSheet()  # noqa: SLF001


def test_embedded_expenses_only_show_mh_category_for_current_month(qtbot: object) -> None:
    view = CalculationView(_ContainerStub())  # type: ignore[arg-type]
    qtbot.addWidget(view)
    view._embedded_expense_period = (date(2026, 11, 1), date(2026, 11, 30))  # noqa: SLF001
    common = dict(
        value_date=date(2026, 11, 5),
        payee="Test",
        purpose="Ausgabe",
        amount=Decimal("-10.00"),
        currency="EUR",
    )

    view._on_embedded_expenses_loaded(  # noqa: SLF001
        [
            BankExpenseRow(transaction_id="mh", position_key="mh", **common),
            BankExpenseRow(transaction_id="xw", position_key="xw", **common),
            BankExpenseRow(
                transaction_id="mh-previous-month",
                position_key="mh",
                **{**common, "value_date": date(2026, 10, 31)},
            ),
        ]
    )

    rows = view._embedded_expenses_table.source_rows_data()  # noqa: SLF001
    assert [row["__transaction_id"] for row in rows] == ["mh"]
    assert "1 MH-Ausgaben im 11.2026" in view._embedded_expenses_status.text()  # noqa: SLF001
