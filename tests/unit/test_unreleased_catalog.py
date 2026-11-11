from __future__ import annotations

import pytest

from xw_office.services.products.catalog import (
    ProductCatalogService,
    _title_match_score,
    split_unreleased_titles,
)


class _FailingSettingsRepo:
    def get_value_json(self, key: str) -> str | None:
        return "[]" if key == "inventory.products" else None

    def mutate_value_json(self, _key: str, _mutator: object) -> str:
        raise RuntimeError("settings database unavailable")

    def set_value_json(self, _key: str, _value: str) -> None:
        raise RuntimeError("settings database unavailable")


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


def test_split_unreleased_titles_discards_standalone_blechhaufn_label() -> None:
    assert split_unreleased_titles(
        ["Chandelier", "Blechhaufn:", "Ich hab dich lieb"], quantity=2
    ) == ["Chandelier", "Ich hab dich lieb"]


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


@pytest.mark.parametrize("operation", ["resolve", "create"])
def test_failed_unreleased_settings_write_does_not_publish_local_override(operation: str) -> None:
    catalog = ProductCatalogService(_FailingSettingsRepo())  # type: ignore[arg-type]
    catalog.list_unreleased_products()

    with pytest.raises(RuntimeError, match="settings database unavailable"):
        if operation == "resolve":
            catalog.save_unreleased_resolution(
                "Unsaved alias", canonical_name="Unsaved product", owner="XeisWorks"
            )
        else:
            catalog.add_or_update_unreleased_product(
                "Unsaved product", owner="XeisWorks", aliases=["Unsaved alias"]
            )

    assert catalog._local_unreleased_overrides == []  # noqa: SLF001
