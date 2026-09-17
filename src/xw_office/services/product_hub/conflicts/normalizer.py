"""Comparison-only normalization.  Canonical values are never mutated here."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import unicodedata
from typing import Any

_PRINT_MARKERS = re.compile(r"(?:\[\s*print\s*\]|🖨️?)", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_TRANSPOSITIONS = {"bb": "b", "b♭": "b", "eb": "es", "e♭": "es"}


def normalize_value(field_path: str, value: Any) -> Any:
    """Return a stable semantic comparison value for one field."""
    if value is None:
        return None
    if field_path in {"price", "price_net", "price_gross", "tax_rate", "vat"}:
        try:
            return str(
                Decimal(str(value).replace(",", ".")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )
        except (InvalidOperation, ValueError):
            pass
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).strip()
        normalized = _PRINT_MARKERS.sub("", normalized)
        normalized = _WHITESPACE.sub(" ", normalized).casefold().strip()
        if field_path in {"transposition", "instrument", "scoring", "name", "title"}:
            words = normalized.split(" ")
            normalized = " ".join(_TRANSPOSITIONS.get(word, word) for word in words)
        return normalized
    if isinstance(value, list):
        return sorted((normalize_value(field_path, item) for item in value), key=str)
    if isinstance(value, dict):
        return {
            key: normalize_value(f"{field_path}.{key}", val) for key, val in sorted(value.items())
        }
    return value


def equivalent(field_path: str, left: Any, right: Any) -> bool:
    return bool(normalize_value(field_path, left) == normalize_value(field_path, right))
