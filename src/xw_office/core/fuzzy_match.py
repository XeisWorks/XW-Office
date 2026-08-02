"""Single fuzzy-matching entry point shared across the app.

Legacy code used ``difflib.SequenceMatcher`` in one module (Ausgaben-Check)
and ``rapidfuzz`` in another (CRM), each hand-tuned separately. This module
standardizes on rapidfuzz — already a project dependency, and faster — so
every caller (CRM matching, Ausgaben-Check ignore rules, unreleased-piece
matching) shares one implementation and a comparable 0..1 scale instead of
each carrying its own threshold and library.
"""
from __future__ import annotations

from rapidfuzz import fuzz


def fuzzy_ratio(a: str, b: str) -> float:
    """Return a 0.0..1.0 similarity ratio for two raw strings."""
    return fuzz.ratio(a or "", b or "") / 100.0


def token_set_ratio(a: str, b: str) -> float:
    """Return a 0.0..1.0 similarity ratio that ignores word order/duplicates."""
    return fuzz.token_set_ratio(a or "", b or "") / 100.0


def is_fuzzy_match(a: str, b: str, *, threshold: float = 0.68) -> bool:
    """True when two strings are similar enough per :func:`fuzzy_ratio`.

    ``0.68`` is the legacy Ausgaben-Check default for recognizing a
    recurring bank transaction whose purpose text varies slightly (e.g. a
    different invoice number each month).
    """
    return fuzzy_ratio(a, b) >= threshold


def best_match(
    needle: str,
    candidates: list[str],
    *,
    threshold: float = 0.68,
) -> tuple[str, float] | None:
    """Return the best-scoring candidate at/above *threshold*, or ``None``."""
    best_candidate = ""
    best_score = 0.0
    for candidate in candidates:
        score = fuzzy_ratio(needle, candidate)
        if score > best_score:
            best_candidate, best_score = candidate, score
    if best_score >= threshold:
        return best_candidate, best_score
    return None
