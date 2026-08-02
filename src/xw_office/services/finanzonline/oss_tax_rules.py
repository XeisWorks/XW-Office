"""Versioned sevDesk tax-rule mapping for EU-OSS classification."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

_DECIMAL_2 = Decimal("0.01")


@dataclass(frozen=True)
class OssTaxRule:
    label: str
    country_code: str
    vat_rate: Decimal
    oss_eligible: bool
    exclude_reason: str = ""


def default_oss_tax_rules_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "oss_tax_rules.json"


def load_oss_tax_rules(path: Path | str | None = None) -> Mapping[str, OssTaxRule]:
    rules_path = Path(path) if path is not None else default_oss_tax_rules_path()
    if not rules_path.exists():
        return MappingProxyType({})
    payload = json.loads(rules_path.read_text(encoding="utf-8"))
    rows = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return MappingProxyType({})

    rules: dict[str, OssTaxRule] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        rule = OssTaxRule(
            label=label,
            country_code=str(row.get("country_code") or "").strip().upper(),
            vat_rate=_decimal(row.get("vat_rate")),
            oss_eligible=bool(row.get("oss_eligible")),
            exclude_reason=str(row.get("exclude_reason") or "").strip(),
        )
        for candidate in _rule_labels(label, row.get("aliases")):
            rules[normalize_tax_rule_label(candidate)] = rule
    return MappingProxyType(rules)


def known_oss_rates_by_country(rules: Mapping[str, OssTaxRule]) -> Mapping[str, frozenset[Decimal]]:
    grouped: dict[str, set[Decimal]] = {}
    for rule in rules.values():
        if not rule.oss_eligible or not rule.country_code:
            continue
        grouped.setdefault(rule.country_code, set()).add(rule.vat_rate)
    return MappingProxyType({country: frozenset(rates) for country, rates in grouped.items()})


def normalize_tax_rule_label(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.upper().replace(",", ".")
    return " ".join(text.split())


def _rule_labels(label: str, aliases: object) -> Iterable[str]:
    yield label
    if isinstance(aliases, list):
        for alias in aliases:
            if str(alias or "").strip():
                yield str(alias)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", ".")).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")
