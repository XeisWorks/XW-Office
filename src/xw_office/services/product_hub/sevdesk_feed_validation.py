"""Strict normalization helpers for sevDesk inventory feeds."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

FeedDocumentState = Literal["draft", "final", "unknown"]

_FINAL_STATUSES = {"200", "750", "1000", "open", "open/due", "partially paid", "paid"}
_DRAFT_STATUSES = {"100", "draft", "entwurf"}


def document_state(document: dict[str, object]) -> FeedDocumentState:
    """Classify only the sevDesk states that are safe for inventory posting."""
    raw = str(document.get("status") or "").strip().casefold()
    if raw in _DRAFT_STATUSES:
        return "draft"
    if raw in _FINAL_STATUSES:
        return "final"
    return "unknown"


def feed_quantity(position: dict[str, object]) -> Decimal | None:
    """Parse a finite, non-negative source quantity without truncating it."""
    raw = position.get("quantity")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = position.get("qty")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        quantity = Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not quantity.is_finite() or quantity < 0:
        return None
    return quantity


__all__ = ["FeedDocumentState", "document_state", "feed_quantity"]
