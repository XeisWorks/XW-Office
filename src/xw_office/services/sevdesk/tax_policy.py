"""TaxSet policy for Lieferkorrektur invoices — mirrors wix-sevdesk-api tax logic (spec §10).

The country -> sevDesk TaxSet mapping (``config/customer_aftercare_tax_set_mapping.json``)
is copied **verbatim** from ``wix-sevdesk-api/src/services/sevdesk.TaxSet.js``
(``TAX_SET_MAPPING``) so XW-Office and wix-sevdesk-api stay in functional
parity without a full sevDesk rewrite (spec §10). wix-sevdesk-api is a
separate, production-critical service and is never modified from here —
this module only reads the same already-approved data. Any *future* change
to the table needs matching tax-advisor sign-off on both sides (see
wix-sevdesk-api's own ``markdowns/01-umbauplan.md``).

Mirrors the exact decision logic from ``sevdesk.Invoice.js::transformWixOrderToInvoice``:
  1. If a TaxSet text is mapped for (country, customer_type) -> use it (``taxType='custom'``).
  2. Else, if the billing country is not AT and the customer is B2B -> sevDesk's
     built-in EU reverse-charge type (``taxType='eu'``).
  3. Else -> sevDesk's domestic default (``taxType='default'``).

Per-line-item ``taxRate`` is **not** derived from this table — on the
wix-sevdesk-api side it always comes from the Wix order's own
``lineItem.taxDetails.taxRate``; the equivalent here is the stored
``CustomerAftercareItem.source_tax_rate``. Callers must preserve a
legitimate 0% rate (B2B reverse-charge / export) rather than silently
defaulting it to a positive rate.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class TaxSetRule:
    country_code: str
    customer_type: str  # "b2b" | "b2c"
    tax_set_text: str


@dataclass(frozen=True)
class TaxDecision:
    """What to write onto the sevDesk invoice for a Lieferkorrektur position's country/customer type."""

    tax_type: str  # "custom" | "eu" | "default"
    tax_set_text: str = ""


def default_tax_set_mapping_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "customer_aftercare_tax_set_mapping.json"


def load_tax_set_mapping(path: Path | str | None = None) -> Mapping[tuple[str, str], TaxSetRule]:
    rules_path = Path(path) if path is not None else default_tax_set_mapping_path()
    if not rules_path.exists():
        return MappingProxyType({})
    payload = json.loads(rules_path.read_text(encoding="utf-8"))
    rows = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return MappingProxyType({})

    rules: dict[tuple[str, str], TaxSetRule] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        country_code = str(row.get("country_code") or "").strip().upper()
        customer_type = str(row.get("customer_type") or "").strip().lower()
        tax_set_text = str(row.get("tax_set_text") or "").strip()
        if not country_code or customer_type not in {"b2b", "b2c"} or not tax_set_text:
            continue
        rules[(country_code, customer_type)] = TaxSetRule(
            country_code=country_code, customer_type=customer_type, tax_set_text=tax_set_text
        )
    return MappingProxyType(rules)


class CustomerAftercareTaxPolicy:
    """Decide the sevDesk taxType/TaxSet for a Lieferkorrektur invoice line (spec §10)."""

    def __init__(self, mapping: Mapping[tuple[str, str], TaxSetRule] | None = None) -> None:
        self._mapping = mapping if mapping is not None else load_tax_set_mapping()

    def resolve(self, *, country_code: str, is_b2b: bool) -> TaxDecision:
        code = str(country_code or "").strip().upper()
        customer_type = "b2b" if is_b2b else "b2c"
        rule = self._mapping.get((code, customer_type))
        if rule is not None:
            return TaxDecision(tax_type="custom", tax_set_text=rule.tax_set_text)
        if code != "AT" and is_b2b:
            return TaxDecision(tax_type="eu")
        return TaxDecision(tax_type="default")
