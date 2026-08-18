"""Tests for CustomerAftercareTaxPolicy (spec §10) — verbatim parity with wix-sevdesk-api.

The mapping table itself is loaded from config/customer_aftercare_tax_set_mapping.json,
which was copied verbatim from wix-sevdesk-api/src/services/sevdesk.TaxSet.js's
TAX_SET_MAPPING. These tests pin down the exact source asymmetry (b2b only
has CH/GB/NO export entries, b2c has the OSS country list, NO is *not* in
the b2c map) so accidental drift from the source is caught.
"""
from __future__ import annotations

from xw_office.services.sevdesk.tax_policy import CustomerAftercareTaxPolicy, load_tax_set_mapping


def _policy() -> CustomerAftercareTaxPolicy:
    return CustomerAftercareTaxPolicy(load_tax_set_mapping())


def test_at_is_absent_from_mapping_and_falls_back_to_default_for_b2b_and_b2c() -> None:
    policy = _policy()
    assert policy.resolve(country_code="AT", is_b2b=True).tax_type == "default"
    assert policy.resolve(country_code="AT", is_b2b=False).tax_type == "default"


def test_ch_gb_no_are_export_tax_free_for_b2b_testmatrix_11() -> None:
    policy = _policy()
    for country in ("CH", "GB", "NO"):
        decision = policy.resolve(country_code=country, is_b2b=True)
        assert decision.tax_type == "custom"
        assert decision.tax_set_text == "Steuerfreie Ausfuhrlieferung (§ 7 UStG 1994)"


def test_ch_gb_are_export_tax_free_for_b2c_but_no_is_not_in_b2c_map() -> None:
    """Pins the exact source asymmetry: NO only appears under b2b, not b2c."""
    policy = _policy()
    assert policy.resolve(country_code="CH", is_b2b=False).tax_type == "custom"
    assert policy.resolve(country_code="GB", is_b2b=False).tax_type == "custom"
    # NO/b2c is not in the source mapping -> not AT, but is_b2b is False -> "default"
    # (the EU reverse-charge fallback only applies to B2B, matching sevdesk.Invoice.js).
    assert policy.resolve(country_code="NO", is_b2b=False).tax_type == "default"


def test_de_b2c_uses_oss_tax_set_text_testmatrix_10() -> None:
    decision = _policy().resolve(country_code="DE", is_b2b=False)
    assert decision.tax_type == "custom"
    assert decision.tax_set_text == "Deutsche MwSt. 7%"


def test_de_b2b_is_not_in_mapping_and_falls_back_to_eu_reverse_charge() -> None:
    """DE has no b2b entry in the source table -> EU reverse charge, not a specific TaxSet."""
    decision = _policy().resolve(country_code="DE", is_b2b=True)
    assert decision.tax_type == "eu"
    assert decision.tax_set_text == ""


def test_unmapped_eu_b2b_country_falls_back_to_eu_reverse_charge() -> None:
    decision = _policy().resolve(country_code="PL", is_b2b=True)
    assert decision.tax_type == "eu"


def test_unmapped_country_b2c_falls_back_to_default() -> None:
    decision = _policy().resolve(country_code="PL", is_b2b=False)
    assert decision.tax_type == "default"


def test_country_code_is_case_insensitive() -> None:
    assert _policy().resolve(country_code="de", is_b2b=False).tax_type == "custom"
