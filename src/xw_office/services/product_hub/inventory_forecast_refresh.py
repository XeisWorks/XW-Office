"""Refresh Product Hub reorder points from finalized sevDesk history."""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from xw_office.repositories.product_hub import ProductFilter, ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.services.product_hub.inventory import DEFAULT_LOCATION_CODE, InventoryV2Service
from xw_office.services.product_hub.inventory_forecast import FinalizedSale, ReorderPointResult
from xw_office.services.product_hub.sevdesk_history_audit import SevdeskHistoryProvider, _parse_date, _position_sku, _position_units


@dataclass
class ForecastRefreshResult:
    refreshed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    results: list[ReorderPointResult] = field(default_factory=list)


class InventoryForecastRefreshService:
    """Recompute every active physical variant without touching sales history."""

    def __init__(
        self, session_factory: sessionmaker[Session], provider: SevdeskHistoryProvider
    ) -> None:
        self._products = ProductHubRepository(session_factory)
        self._inventory = InventoryRepository(session_factory)
        self._service = InventoryV2Service(session_factory)
        self._provider = provider

    def refresh(self, *, as_of: dt.date | None = None, years: int = 5) -> ForecastRefreshResult:
        as_of = as_of or dt.date.today()
        window_start = _window_start(as_of, years)
        history = self._load_history(window_start=window_start, as_of=as_of)
        result = ForecastRefreshResult()
        products = self._products.list_products(ProductFilter(status="live", active=True))
        variants = self._products.list_variants_for_products([product.id for product in products])
        product_by_id = {product.id: product for product in products}
        location = self._inventory.get_or_create_location(code=DEFAULT_LOCATION_CODE, name="Hauptlager")
        for variant in variants:
            product = product_by_id.get(variant.product_id)
            if product is None or not variant.active or not variant.stock_enabled or product.product_type == "digital":
                result.skipped += 1
                continue
            stock = self._inventory.get_stock(variant.id, location.id)
            fixed = stock.reorder_point if stock is not None and stock.reorder_mode == "fixed" else None
            try:
                forecast = self._service.refresh_reorder_point(
                    variant_id=variant.id,
                    sales=history.get(variant.sku.strip().upper(), []),
                    as_of=as_of,
                    sellable_since=product.release_date,
                    fixed_reorder_point=fixed,
                )
            except Exception as exc:  # noqa: BLE001 - continue independent variants
                result.errors.append(f"{variant.sku}: {exc}")
                continue
            result.refreshed += 1
            result.results.append(forecast)
        return result

    def _load_history(self, *, window_start: dt.date, as_of: dt.date) -> dict[str, list[FinalizedSale]]:
        history: dict[str, list[FinalizedSale]] = {}
        for year in range(window_start.year, as_of.year + 1):
            for document, positions, signed in self._documents_for_year(year):
                occurred_on = _parse_date(document, ("invoiceDate", "creditNoteDate", "date", "create", "updated"))
                if occurred_on is None or occurred_on < window_start or occurred_on >= as_of.replace(day=1):
                    continue
                for position in positions:
                    sku = _position_sku(position).upper()
                    quantity = _position_units(position)
                    if not sku or quantity <= 0:
                        continue
                    history.setdefault(sku, []).append(
                        FinalizedSale(sku=sku, occurred_on=occurred_on, quantity=signed * quantity)
                    )
        return history

    def _documents_for_year(
        self, year: int
    ) -> Iterator[tuple[dict[str, Any], list[dict[str, Any]], int]]:
        for document in self._provider.list_invoices_for_year(year):
            if not _is_draft(document):
                yield document, self._provider.list_invoice_positions(str(document.get("id") or "")), 1
        for document in self._provider.list_credit_notes_for_year(year):
            if not _is_draft(document):
                yield document, self._provider.list_credit_note_positions(str(document.get("id") or "")), -1


def _is_draft(document: dict[str, Any]) -> bool:
    status = document.get("status")
    if not isinstance(status, (int, float, str)):
        status = ""
    try:
        return int(status) == 100
    except (TypeError, ValueError):
        return str(document.get("status") or "").strip().casefold() in {"draft", "entwurf"}


def _window_start(as_of: dt.date, years: int) -> dt.date:
    end = as_of.replace(day=1)
    index = end.year * 12 + end.month - 1 - (years * 12 - 1)
    return dt.date(index // 12, index % 12 + 1, 1)


__all__ = ["ForecastRefreshResult", "InventoryForecastRefreshService"]
