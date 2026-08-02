"""Tests for direct B2B bank-transfer invoice reference extraction."""
from __future__ import annotations

from xw_office.services.clearing.b2b_reference import extract_b2b_invoice_numbers

YEARS = ("24", "25", "26", "27")


def test_extracts_single_six_digit_invoice_number() -> None:
    result = extract_b2b_invoice_numbers("Zahlung RE-261234 danke", year_prefixes=YEARS)
    assert result == ("RE-261234",)


def test_extracts_bare_six_digit_number_without_prefix() -> None:
    result = extract_b2b_invoice_numbers("Rechnung 261234 Musikkapelle", year_prefixes=YEARS)
    assert result == ("RE-261234",)


def test_rejects_year_outside_allowed_prefixes() -> None:
    result = extract_b2b_invoice_numbers("Rechnung 991234", year_prefixes=YEARS)
    assert result == ()


def test_ignores_five_digit_wix_order_numbers() -> None:
    result = extract_b2b_invoice_numbers("Bestellung 12345", year_prefixes=YEARS)
    assert result == ()


def test_ignores_seven_digit_runs() -> None:
    result = extract_b2b_invoice_numbers("IBAN-Fragment 2612345", year_prefixes=YEARS)
    assert result == ()


def test_extracts_multiple_distinct_invoices_in_order() -> None:
    result = extract_b2b_invoice_numbers(
        "Sammelueberweisung RE-261001 und RE-261002", year_prefixes=YEARS
    )
    assert result == ("RE-261001", "RE-261002")


def test_deduplicates_repeated_reference() -> None:
    result = extract_b2b_invoice_numbers("RE-261234 RE-261234", year_prefixes=YEARS)
    assert result == ("RE-261234",)


def test_empty_purpose_returns_empty_tuple() -> None:
    assert extract_b2b_invoice_numbers("", year_prefixes=YEARS) == ()


def test_empty_year_prefixes_returns_empty_tuple() -> None:
    assert extract_b2b_invoice_numbers("RE-261234", year_prefixes=()) == ()
