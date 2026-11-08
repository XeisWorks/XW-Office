"""Deterministic reorder-point calculation for physical note variants."""
from __future__ import annotations

import calendar
import datetime as dt
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FinalizedSale:
    """One final sevDesk line contribution for one exact variant."""

    sku: str
    occurred_on: dt.date
    quantity: int
    finalized: bool = True


@dataclass(frozen=True)
class ReorderPointResult:
    sku: str
    active_reorder_point: int
    automatic_reorder_point: int
    fixed_reorder_point: int | None
    net_sold_units: int
    full_sellable_months: int
    window_start: dt.date
    window_end: dt.date
    used_initial_value: bool
    data_quality: str


def calculate_reorder_point(
    *,
    sku: str,
    sales: list[FinalizedSale] | tuple[FinalizedSale, ...],
    as_of: dt.date,
    sellable_since: dt.date | None,
    fixed_reorder_point: int | None = None,
    initial_reorder_point: int = 50,
    minimum_history_months: int = 6,
    horizon_months: int = 3,
    window_months: int = 60,
) -> ReorderPointResult:
    """Calculate the active reorder point without performing any I/O.

    The current partial calendar month is excluded.  ``quantity`` is signed so
    finalized credit-note quantities can be represented as negative values.  A
    fixed value affects only the active threshold; the automatic proposal remains
    available to the UI.  Invalid parameters raise ``ValueError`` instead of being
    silently coerced into an unsafe stock policy.
    """
    if not str(sku or "").strip():
        raise ValueError("SKU ist erforderlich")
    if initial_reorder_point < 0 or minimum_history_months < 1 or horizon_months < 1 or window_months < 1:
        raise ValueError("Forecast-Parameter sind ungültig")
    if as_of is None:
        raise ValueError("as_of ist erforderlich")

    current_month = as_of.replace(day=1)
    window_end = _shift_month(current_month, -1)
    window_start = _shift_month(window_end, -(window_months - 1))
    sellable_month = _month_start(sellable_since) if sellable_since is not None else None
    history_start = max(window_start, sellable_month) if sellable_month is not None else window_start
    full_months = _month_distance(history_start, window_end) if history_start <= window_end else 0

    normalized_sku = str(sku).strip().upper()
    net_sold = sum(
        int(item.quantity)
        for item in sales
        if item.finalized
        and str(item.sku or "").strip().upper() == normalized_sku
        and window_start <= item.occurred_on <= _month_end(window_end)
        and (sellable_month is None or item.occurred_on >= sellable_month)
    )
    net_sold = max(0, net_sold)
    # Without a trusted start date the automatic window cannot prove six full
    # sellable months. Keep the conservative initial value until that data gap is
    # resolved, while still exposing the computed window for diagnostics.
    used_initial = sellable_since is None or full_months < minimum_history_months
    automatic = (
        initial_reorder_point
        if used_initial
        else math.ceil(net_sold / full_months * horizon_months)
    )
    active = max(0, int(fixed_reorder_point)) if fixed_reorder_point is not None else automatic
    quality = "insufficient_history" if used_initial else "complete_month_window"
    if sellable_since is None:
        quality = "missing_sellable_since"
    return ReorderPointResult(
        sku=normalized_sku,
        active_reorder_point=active,
        automatic_reorder_point=automatic,
        fixed_reorder_point=fixed_reorder_point,
        net_sold_units=net_sold,
        full_sellable_months=full_months,
        window_start=window_start,
        window_end=_month_end(window_end),
        used_initial_value=used_initial,
        data_quality=quality,
    )


def _month_start(value: dt.date) -> dt.date:
    return value.replace(day=1)


def _month_end(value: dt.date) -> dt.date:
    last_day = calendar.monthrange(value.year, value.month)[1]
    return value.replace(day=last_day)


def _month_distance(start: dt.date, end: dt.date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def _shift_month(value: dt.date, delta: int) -> dt.date:
    index = value.year * 12 + value.month - 1 + delta
    year, month_index = divmod(index, 12)
    return dt.date(year, month_index + 1, 1)


__all__ = ["FinalizedSale", "ReorderPointResult", "calculate_reorder_point"]
