from __future__ import annotations

import datetime as dt

import pytest

from xw_office.services.product_hub.inventory_forecast import FinalizedSale, calculate_reorder_point


def test_new_product_uses_fifty_until_six_full_months() -> None:
    result = calculate_reorder_point(
        sku="N-001",
        sales=[],
        as_of=dt.date(2026, 7, 15),
        sellable_since=dt.date(2026, 1, 10),
    )

    assert result.window_end == dt.date(2026, 6, 30)
    assert result.full_sellable_months == 6
    assert result.active_reorder_point == 0
    assert result.used_initial_value is False


def test_five_month_history_uses_initial_value_and_fixed_value_overrides() -> None:
    result = calculate_reorder_point(
        sku="N-001",
        sales=[],
        as_of=dt.date(2026, 6, 20),
        sellable_since=dt.date(2026, 1, 1),
        fixed_reorder_point=12,
    )

    assert result.full_sellable_months == 5
    assert result.automatic_reorder_point == 50
    assert result.active_reorder_point == 12
    assert result.used_initial_value is True


def test_forecast_excludes_current_partial_month_and_applies_credits() -> None:
    result = calculate_reorder_point(
        sku="N-001",
        sales=[
            FinalizedSale("N-001", dt.date(2026, 1, 5), 10),
            FinalizedSale("N-001", dt.date(2026, 2, 5), 2),
            FinalizedSale("N-001", dt.date(2026, 2, 20), -1),
            FinalizedSale("N-001", dt.date(2026, 3, 3), 99, finalized=False),
            FinalizedSale("OTHER", dt.date(2026, 2, 3), 100),
        ],
        as_of=dt.date(2026, 4, 10),
        sellable_since=dt.date(2025, 1, 1),
    )

    assert result.window_end == dt.date(2026, 3, 31)
    assert result.net_sold_units == 11
    assert result.full_sellable_months == 15
    assert result.automatic_reorder_point == 3


def test_missing_sellable_date_is_visible_in_quality() -> None:
    result = calculate_reorder_point(
        sku="N-001",
        sales=[FinalizedSale("N-001", dt.date(2026, 1, 1), 1)],
        as_of=dt.date(2026, 4, 10),
        sellable_since=None,
    )

    assert result.used_initial_value is True
    assert result.active_reorder_point == 50
    assert result.data_quality == "missing_sellable_since"


def test_invalid_parameters_raise() -> None:
    with pytest.raises(ValueError):
        calculate_reorder_point(
            sku="N-001",
            sales=[],
            as_of=dt.date(2026, 4, 10),
            sellable_since=None,
            horizon_months=0,
        )
