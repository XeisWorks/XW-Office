from __future__ import annotations

from xw_office.services.wix.identifiers import canonical_wix_id, is_valid_wix_id


def test_canonical_wix_id_accepts_legacy_prefixes() -> None:
    assert canonical_wix_id("product_abc-123") == "abc-123"
    assert canonical_wix_id("variant_abc-123") == "abc-123"
    assert is_valid_wix_id("product_abc-123") is True


def test_canonical_wix_id_rejects_composite_reference() -> None:
    assert canonical_wix_id("product_one|product_two") == ""
    assert is_valid_wix_id("product_one|product_two") is False
