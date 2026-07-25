"""Centralized reference/SKU classification rules.

Legacy scattered small-but-load-bearing conventions (B2B/B2C reference
prefix) ad hoc across ``invoice_processor.py``, the refund flow, and PLC
labeling, each reimplementing its own prefix check. This module gives
fulfillment, refunds, and PLC one shared, tested source of truth instead of
three independent copies.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xw_studio.core.config import SkuRulesSection


class ReferenceClass(str, Enum):
    """Business-channel classification of a sevDesk/Wix order reference."""

    B2B = "b2b"
    B2C = "b2c"
    UNKNOWN = "unknown"


def classify_reference(
    reference: str,
    *,
    b2b_prefixes: Sequence[str],
    b2c_prefixes: Sequence[str],
) -> ReferenceClass:
    """Classify one order/invoice reference by its configured prefix.

    Legacy convention: references starting with "1" are B2B, references
    starting with "2" are B2C. Prefixes are configurable (see
    :class:`~xw_studio.core.config.SkuRulesSection`) since the convention
    is a business decision, not a code constant. B2B prefixes are checked
    first so an overlapping configuration is not ambiguous.
    """
    text = str(reference or "").strip()
    if not text:
        return ReferenceClass.UNKNOWN
    for prefix in b2b_prefixes:
        if prefix and text.startswith(prefix):
            return ReferenceClass.B2B
    for prefix in b2c_prefixes:
        if prefix and text.startswith(prefix):
            return ReferenceClass.B2C
    return ReferenceClass.UNKNOWN


@dataclass(frozen=True)
class ReferenceClassifier:
    """Config-bound classifier — resolve once via DI, reuse everywhere.

    Fulfillment, refunds, and PLC labeling should all depend on this one
    instance instead of each re-reading ``sku_rules`` and re-implementing
    the prefix check.
    """

    b2b_prefixes: tuple[str, ...]
    b2c_prefixes: tuple[str, ...]

    @classmethod
    def from_config(cls, config: "SkuRulesSection") -> "ReferenceClassifier":
        return cls(
            b2b_prefixes=tuple(config.b2b_reference_prefixes),
            b2c_prefixes=tuple(config.b2c_reference_prefixes),
        )

    def classify(self, reference: str) -> ReferenceClass:
        return classify_reference(
            reference,
            b2b_prefixes=self.b2b_prefixes,
            b2c_prefixes=self.b2c_prefixes,
        )
