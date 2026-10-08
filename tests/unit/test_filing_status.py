from __future__ import annotations

from xw_office.services.finanzonline.filing_status import (
    FilingStatusStore,
    oss_calculation_hash,
    uva_calculation_hash,
)


def test_filing_status_is_persistent_and_tied_to_calculation_hash(tmp_path) -> None:
    path = tmp_path / "tax.sqlite"
    store = FilingStatusStore(path)
    first_hash = "a" * 64
    second_hash = "b" * 64

    store.record_submission(
        "uva", 2026, 9, first_hash,
        confirmation_source="finanzonline_production_response",
        reference="FON-123",
    )

    reopened = FilingStatusStore(path)
    first = reopened.get_status("uva", 2026, 9, first_hash)
    changed = reopened.get_status("uva", 2026, 9, second_hash)
    assert first is not None
    assert first.confirmation_source == "finanzonline_production_response"
    assert first.reference == "FON-123"
    assert changed is None


def test_uva_fingerprint_uses_the_exact_u30_values() -> None:
    calculated = {
        "jahr": 2026,
        "monat": 9,
        "kennzahlen": {"A000": "100.00", "A029": "10.00"},
        "zahlbetrag": "90.00",
        "rule_version": "U30_01_2022",
    }
    submitted = {
        **calculated,
        "kennzahlen": {"KZ000": "100.00", "KZ029": "10.00"},
    }
    assert uva_calculation_hash(calculated) == uva_calculation_hash(submitted)
    assert uva_calculation_hash({**calculated, "zahlbetrag": "89.99"}) != uva_calculation_hash(calculated)


def test_oss_fingerprint_ignores_cache_metadata_only() -> None:
    payload = {"year": 2026, "quarter": 3, "tax": "466.86"}
    assert oss_calculation_hash({**payload, "cache": {"age_seconds": 1}}) == oss_calculation_hash(payload)
    assert oss_calculation_hash({**payload, "tax": "466.87"}) != oss_calculation_hash(payload)
