"""Canonical handling of Wix product and variant references.

Historic Wix exports use ``product_<guid>`` while REST endpoints return bare
GUIDs.  A mapping must always refer to exactly one resource; pipe-separated
legacy values are therefore invalid rather than an alternative spelling.
"""

from __future__ import annotations


def canonical_wix_id(value: object) -> str:
    """Return a comparable bare Wix ID, or ``""`` for an invalid reference."""
    text = str(value or "").strip()
    if not text or "|" in text or any(char.isspace() for char in text):
        return ""
    lowered = text.casefold()
    for prefix in ("product_", "variant_"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.strip()


def is_valid_wix_id(value: object) -> bool:
    """Whether a value denotes one usable Wix resource reference."""
    return bool(canonical_wix_id(value))
