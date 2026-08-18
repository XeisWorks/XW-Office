"""Pricing policy for Lieferkorrektur invoices: Kulanz vs. normale Wix-B2B-Konditionen (spec §9).

"Keine Preislogik im UI" — this is the single place that decides the
product/shipping discount percentage for a Lieferkorrektur invoice line.
Courtesy ("Kulanz") always uses the fixed percentages from
``customer_aftercare.courtesy`` config (spec: exactly 30 % product / 100 %
shipping). Non-courtesy passes through whatever discount already applies on
the Wix order context unchanged — this module never computes or reinterprets
Wix B2B discount/shipping rules itself, it only decides *which* number to
use.
"""
from __future__ import annotations

from dataclasses import dataclass

from xw_office.core.config import CustomerAftercareSection


@dataclass(frozen=True)
class DiscountResult:
    """A percentage discount to apply to a sevDesk invoice position."""

    percent: float
    is_percentage: bool = True
    source: str = ""  # "courtesy" | "wix_b2b_rules" | "existing_wix_shipping_logic"


class CustomerAftercarePricingPolicy:
    """Resolve product/shipping discounts for a Lieferkorrektur invoice (spec §9)."""

    def __init__(self, config: CustomerAftercareSection) -> None:
        self._config = config

    def resolve_product_discount(
        self, *, courtesy: bool, order_context_discount_percent: float | None = None
    ) -> DiscountResult:
        if courtesy:
            return DiscountResult(
                percent=float(self._config.courtesy.product_discount_percent),
                source="courtesy",
            )
        return DiscountResult(
            percent=float(order_context_discount_percent or 0.0),
            source="wix_b2b_rules",
        )

    def resolve_shipping_discount(
        self, *, courtesy: bool, order_context_shipping_discount_percent: float | None = None
    ) -> DiscountResult:
        if courtesy:
            return DiscountResult(
                percent=float(self._config.courtesy.shipping_discount_percent),
                source="courtesy",
            )
        return DiscountResult(
            percent=float(order_context_shipping_discount_percent or 0.0),
            source="existing_wix_shipping_logic",
        )
