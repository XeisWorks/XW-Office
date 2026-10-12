from __future__ import annotations

from xw_office.services.products.catalog import ProductCatalogService, _title_match_score


def test_unreleased_title_distinct_versions_do_not_collide() -> None:
    catalog = ProductCatalogService()
    catalog.add_or_update_unreleased_product(
        "Gabriellas Song BH",
        owner="Albert",
        aliases=["Gabriellas Song (BH Version)", "da Blechhauf'n - Gabriella's Song"],
    )
    catalog.add_or_update_unreleased_product(
        "Gabriellas Song XXL",
        owner="Albert",
        aliases=["Gabriellas Song (XXL Version)", "Gabriellas Song XXL"],
    )

    res_bh = catalog.resolve_unreleased_title("Gabriellas Song (BH Version)")
    res_xxl = catalog.resolve_unreleased_title("Gabriellas Song (XXL Version)")

    assert res_bh.is_resolved
    assert res_bh.canonical_name == "Gabriellas Song BH"
    assert res_xxl.is_resolved
    assert res_xxl.canonical_name == "Gabriellas Song XXL"

    # Verify that searching for XXL does not match BH due to version marker conflict
    assert _title_match_score("Gabriellas Song BH", "Gabriellas Song XXL") == 0.0


def test_add_and_delete_unreleased_product() -> None:
    catalog = ProductCatalogService()
    canonical = "Test Unique Unreleased Title 123"
    catalog.add_or_update_unreleased_product(
        canonical,
        owner="XeisWorks",
        aliases=["Test Alias 1", "Test Alias 2"],
    )

    found = next((p for p in catalog.list_unreleased_products() if p.canonical_name == canonical), None)
    assert found is not None
    assert found.owners == ("XeisWorks",)
    assert "Test Alias 1" in found.aliases

    res = catalog.resolve_unreleased_title("Test Alias 1")
    assert res.is_resolved
    assert res.canonical_name == canonical

    catalog.delete_unreleased_product(canonical)
    found_after = next((p for p in catalog.list_unreleased_products() if p.canonical_name == canonical), None)
    assert found_after is None
