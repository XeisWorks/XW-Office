"""Shared stock and print policy calculations.

Keeping these rules pure makes the invoice planner, product UI, and future Hub
worker agree on quantities before any printer or ledger side effect occurs.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ArticleKind(StrEnum):
    EXTERNAL_PRINT = "external_print"
    POD = "pod"
    DIGITAL = "digital"


@dataclass(frozen=True)
class StockAvailability:
    on_hand: int
    reserved: int

    @property
    def available(self) -> int:
        return max(0, int(self.on_hand) - int(self.reserved))


@dataclass(frozen=True)
class PrintPlan:
    article_kind: ArticleKind
    demand: int
    available_before: int
    consume_from_stock: int
    print_qty: int
    shortage: int
    reason: str


def build_print_plan(
    *,
    article_kind: ArticleKind | str,
    demand: int,
    availability: StockAvailability,
    pod_batch_qty: int = 3,
) -> PrintPlan:
    """Plan stock consumption and production without changing stock.

    External-print items never trigger an automatic local production run; their
    shortage is a replenishment signal. POD items print whole batches, while
    digital items have no physical demand. Negative inputs are rejected so callers
    cannot accidentally hide an accounting error by clamping it.
    """
    kind = ArticleKind(str(article_kind))
    if demand < 0 or availability.on_hand < 0 or availability.reserved < 0:
        raise ValueError("Bestands- und Bedarfsmengen dürfen nicht negativ sein")
    if pod_batch_qty <= 0:
        raise ValueError("POD-Druckcharge muss größer als 0 sein")
    requested = int(demand)
    available = availability.available
    if kind is ArticleKind.DIGITAL:
        return PrintPlan(kind, requested, available, 0, 0, 0, "digital")

    consume = min(requested, available)
    shortage = requested - consume
    if shortage == 0:
        return PrintPlan(kind, requested, available, consume, 0, 0, "lager")
    if kind is ArticleKind.EXTERNAL_PRINT:
        return PrintPlan(kind, requested, available, consume, 0, shortage, "replenishment")
    batches = ((shortage + pod_batch_qty - 1) // pod_batch_qty) * pod_batch_qty
    return PrintPlan(kind, requested, available, consume, batches, shortage, "pod_batch")


__all__ = ["ArticleKind", "PrintPlan", "StockAvailability", "build_print_plan"]
