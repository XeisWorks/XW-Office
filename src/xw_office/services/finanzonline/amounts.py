"""Strict decimal parsing for tax calculations and submission."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


def tax_amount(value: object) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    try:
        amount = Decimal(str(value).strip().replace(" ", "").replace(",", "."))
        if not amount.is_finite():
            raise ValueError(f"Nicht endlicher Steuerbetrag: {value!r}")
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"Ungueltiger Steuerbetrag: {value!r}") from exc


def first_amount(document: dict[str, Any], *keys: str) -> Decimal:
    for key in keys:
        if key in document and document.get(key) not in (None, ""):
            return tax_amount(document.get(key))
    return Decimal("0.00")


def document_amounts(document: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    gross = first_amount(document, "sumGrossAccounting", "sumGross", "sumGrossForeignCurrency")
    net = first_amount(document, "sumNetAccounting", "sumNet")
    vat = first_amount(document, "sumTaxAccounting", "sumTax")
    if net == Decimal("0.00") and gross != Decimal("0.00"):
        net = gross - vat
    if vat == Decimal("0.00") and gross != Decimal("0.00") and net != Decimal("0.00"):
        vat = gross - net
    return gross, net, vat


def position_rate(position: dict[str, Any]) -> Decimal:
    for key in ("taxRate", "taxRatePercent", "taxRatePercentage", "taxPercent", "taxPercentage"):
        value = position.get(key)
        if value not in (None, ""):
            return tax_amount(value)
    tax = position.get("tax")
    if isinstance(tax, dict):
        for key in ("rate", "percentage"):
            value = tax.get(key)
            if value not in (None, ""):
                return tax_amount(value)
    return Decimal("0.00")


def position_amounts(position: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    net_keys = ("sumNetAccounting", "sumNet", "amountNet", "priceNet", "priceNetAccounting", "net")
    net = first_amount(position, *net_keys)
    vat = first_amount(position, "sumTaxAccounting", "sumTax")
    if not any(position.get(key) not in (None, "") for key in net_keys):
        net = tax_amount(position.get("quantity") or 1) * tax_amount(position.get("price") or 0)
    if vat == Decimal("0.00") and net != Decimal("0.00"):
        rate = position_rate(position)
        if rate > Decimal("0.00"):
            vat = (net * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return (net + vat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), net, vat
