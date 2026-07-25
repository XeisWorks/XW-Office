"""Tests for the shared fuzzy-matching utility."""
from __future__ import annotations

from xw_studio.core.fuzzy_match import best_match, fuzzy_ratio, is_fuzzy_match, token_set_ratio


def test_fuzzy_ratio_identical_strings_is_one() -> None:
    assert fuzzy_ratio("Miete Buero", "Miete Buero") == 1.0


def test_fuzzy_ratio_completely_different_strings_is_low() -> None:
    assert fuzzy_ratio("Miete Buero", "xyz") < 0.3


def test_is_fuzzy_match_recognizes_recurring_payment_with_varying_reference() -> None:
    # Same recurring payment; only the invoice number differs each month —
    # this is the exact legacy Ausgaben-Check scenario the 0.68 default targets.
    assert is_fuzzy_match("Miete Buero RE 100234", "Miete Buero RE 100999")


def test_is_fuzzy_match_respects_custom_threshold() -> None:
    assert not is_fuzzy_match("Miete Buero", "Miete Lager", threshold=0.95)


def test_token_set_ratio_ignores_word_order() -> None:
    assert token_set_ratio("Buero Miete", "Miete Buero") == 1.0


def test_best_match_returns_highest_scoring_candidate_above_threshold() -> None:
    result = best_match("Miete Buero RE 100234", ["Strom", "Miete Buero RE 100999", "Telefon"])
    assert result is not None
    candidate, score = result
    assert candidate == "Miete Buero RE 100999"
    assert score >= 0.68


def test_best_match_returns_none_when_nothing_meets_threshold() -> None:
    assert best_match("Miete Buero", ["Strom", "Telefon"]) is None


def test_best_match_returns_none_for_empty_candidates() -> None:
    assert best_match("Miete Buero", []) is None
