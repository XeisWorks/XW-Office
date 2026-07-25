"""Tests for shared German text normalization utilities."""
from __future__ import annotations

from xw_studio.core.text_normalize import clean_bank_purpose, normalize_german_text


def test_normalize_german_text_transliterates_umlauts() -> None:
    assert normalize_german_text("Müller") == "mueller"
    assert normalize_german_text("Straße") == "strasse"


def test_normalize_german_text_matches_case_and_accent_variants() -> None:
    assert normalize_german_text("MÜLLER") == normalize_german_text("mueller")


def test_normalize_german_text_strips_punctuation_and_collapses_whitespace() -> None:
    assert normalize_german_text("  Rechnung  Nr. 123!  ") == "rechnung nr 123"


def test_normalize_german_text_handles_empty_input() -> None:
    assert normalize_german_text("") == ""
    assert normalize_german_text(None) == ""  # type: ignore[arg-type]


def test_clean_bank_purpose_removes_sepa_mandate_reference() -> None:
    cleaned = clean_bank_purpose("Miete OG/AB12CD34 Buero")
    assert "OG/AB12CD34" not in cleaned
    assert "Miete" in cleaned and "Buero" in cleaned


def test_clean_bank_purpose_removes_iban_token() -> None:
    cleaned = clean_bank_purpose("Ueberweisung AT611904300234573201 Miete")
    assert "AT611904300234573201" not in cleaned


def test_clean_bank_purpose_removes_date_and_time_tokens() -> None:
    cleaned = clean_bank_purpose("Zahlung vom 24.03.2026 um 14:32 Buero")
    assert "24.03.2026" not in cleaned
    assert "14:32" not in cleaned


def test_clean_bank_purpose_keeps_unrelated_text_intact() -> None:
    assert clean_bank_purpose("Miete Buero Maerz") == "Miete Buero Maerz"
