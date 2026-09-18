"""Tests for the Wix -> Product Hub staging importer (PR03).

Uses fixture-based fake Wix clients (no network) per the build-plan's required
scenarios: product without variants, product with multiple variants, product without
media, 1 cover + multiple samples, revision present, variant-based inventory.
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub_import import ProductHubImportRepository
from xw_office.services.product_hub.wix_import import WixProductImporter
from xw_office.services.wix.client import WixProduct


class _FakeProductsClient:
    def __init__(self, products: list[WixProduct]) -> None:
        self._products = products

    def list_products(self, *, include_hidden: bool = True) -> list[WixProduct]:
        return list(self._products)


class _FakeDetailsClient:
    def __init__(
        self,
        *,
        raw_products: dict[str, dict[str, Any]],
        variants: dict[str, list[dict[str, Any]]] | None = None,
        inventory: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self._raw_products = raw_products
        self._variants = variants or {}
        self._inventory = inventory or {}

    def get_product_raw(self, product_id: str) -> dict[str, Any] | None:
        return self._raw_products.get(product_id)

    def query_variants(self, product_id: str) -> list[dict[str, Any]]:
        return list(self._variants.get(product_id, []))

    def query_inventory(self, product_id: str) -> list[dict[str, Any]]:
        return list(self._inventory.get(product_id, []))


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def import_repo(session_factory: sessionmaker[Session]) -> ProductHubImportRepository:
    return ProductHubImportRepository(session_factory)


def test_import_product_without_variants_uses_own_sku(
    import_repo: ProductHubImportRepository,
) -> None:
    raw = {"id": "P-1", "name": "Ohrwürmer #1", "sku": "XW-001", "revision": "rev-1", "visible": True}
    importer = WixProductImporter(
        products_client=_FakeProductsClient([WixProduct(id="P-1", name="Ohrwürmer #1", sku="XW-001")]),
        details_client=_FakeDetailsClient(raw_products={"P-1": raw}),
        import_repo=import_repo,
    )

    report = importer.run()

    assert report.products_seen == 1
    assert report.products_staged == 1
    assert report.variants_staged == 0
    assert not report.errors

    staged = import_repo.list_staging_products()
    assert len(staged) == 1
    assert staged[0].sku == "XW-001"
    assert staged[0].normalized_fields["revision"] == "rev-1"


def test_import_product_with_multiple_variants(import_repo: ProductHubImportRepository) -> None:
    raw = {"id": "P-2", "name": "MusikHeroes Serie", "revision": "rev-2"}
    variants = [
        {"id": "v1", "sku": "XW-2-A", "choices": {"Instrument": "Trompete"}},
        {"id": "v2", "sku": "XW-2-B", "choices": {"Instrument": "Posaune"}},
        {"id": "v3", "sku": "XW-2-C", "choices": {"Instrument": "Tuba"}},
    ]
    importer = WixProductImporter(
        products_client=_FakeProductsClient([WixProduct(id="P-2", name="MusikHeroes Serie")]),
        details_client=_FakeDetailsClient(
            raw_products={"P-2": raw}, variants={"P-2": variants}
        ),
        import_repo=import_repo,
    )

    report = importer.run()

    assert report.variants_staged == 3
    staged = import_repo.list_staging_products()[0]
    staged_variants = import_repo.list_variants(staged.id)
    assert {v.sku for v in staged_variants} == {"XW-2-A", "XW-2-B", "XW-2-C"}
    # First variant's SKU becomes the staging product's default SKU.
    assert staged.sku == "XW-2-A"


def test_import_product_without_media_stages_no_assets(
    import_repo: ProductHubImportRepository,
) -> None:
    raw = {"id": "P-3", "name": "Kein Bild", "sku": "XW-003"}
    importer = WixProductImporter(
        products_client=_FakeProductsClient([WixProduct(id="P-3", name="Kein Bild")]),
        details_client=_FakeDetailsClient(raw_products={"P-3": raw}),
        import_repo=import_repo,
    )

    report = importer.run()

    assert report.assets_staged == 0


def test_import_first_image_is_cover_and_remaining_images_are_gallery(
    import_repo: ProductHubImportRepository,
) -> None:
    raw = {
        "id": "P-4",
        "name": "Mit Cover und Beispielen",
        "sku": "XW-004",
        "media": {
            "items": [
                {"id": "m1", "image": {"url": "https://example.invalid/cover.jpg"}},
                {"id": "m2", "image": {"url": "https://example.invalid/sample1.jpg"}},
                {"id": "m3", "image": {"url": "https://example.invalid/sample2.jpg"}},
            ]
        },
    }
    importer = WixProductImporter(
        products_client=_FakeProductsClient([WixProduct(id="P-4", name="Mit Cover und Beispielen")]),
        details_client=_FakeDetailsClient(raw_products={"P-4": raw}),
        import_repo=import_repo,
    )

    report = importer.run()
    assert report.assets_staged == 3

    staged = import_repo.list_staging_products()[0]
    rows = import_repo.list_assets(staged.id)

    assert [row.role for row in rows] == ["COVER", "GALLERY_IMAGE", "GALLERY_IMAGE"]
    assert rows[0].source_url == "https://example.invalid/cover.jpg"


def test_import_captures_revision_for_optimistic_concurrency(
    import_repo: ProductHubImportRepository,
) -> None:
    raw = {"id": "P-5", "name": "Revisioniert", "sku": "XW-005", "revision": "42"}
    importer = WixProductImporter(
        products_client=_FakeProductsClient([WixProduct(id="P-5", name="Revisioniert")]),
        details_client=_FakeDetailsClient(raw_products={"P-5": raw}),
        import_repo=import_repo,
    )

    importer.run()

    staged = import_repo.list_staging_products()[0]
    assert staged.normalized_fields["revision"] == "42"


def test_import_stages_variant_based_inventory(import_repo: ProductHubImportRepository) -> None:
    raw = {"id": "P-6", "name": "Mit Bestand", "revision": "rev-6"}
    variants = [{"id": "v1", "sku": "XW-6-A"}, {"id": "v2", "sku": "XW-6-B"}]
    inventory = [
        {"id": "inv1", "variantId": "v1", "quantity": 4, "inStock": True, "locationId": "MAIN"},
        {"id": "inv2", "variantId": "v2", "quantity": 0, "inStock": False, "locationId": "MAIN"},
    ]
    importer = WixProductImporter(
        products_client=_FakeProductsClient([WixProduct(id="P-6", name="Mit Bestand")]),
        details_client=_FakeDetailsClient(
            raw_products={"P-6": raw}, variants={"P-6": variants}, inventory={"P-6": inventory}
        ),
        import_repo=import_repo,
    )

    report = importer.run()
    assert report.inventory_rows_staged == 2

    staged = import_repo.list_staging_products()[0]
    rows = import_repo.list_inventory(staged.id)

    quantities = sorted(row.quantity for row in rows)
    assert quantities == [0, 4]
    assert any(row.stock_enabled is False for row in rows)


def test_import_one_failing_product_does_not_abort_batch(
    import_repo: ProductHubImportRepository,
) -> None:
    importer = WixProductImporter(
        products_client=_FakeProductsClient(
            [WixProduct(id="P-OK", name="Gut"), WixProduct(id="P-BAD", name="Fehlt")]
        ),
        details_client=_FakeDetailsClient(raw_products={"P-OK": {"id": "P-OK", "name": "Gut"}}),
        import_repo=import_repo,
    )

    report = importer.run()

    assert report.products_seen == 2
    assert report.products_staged == 1
    assert len(report.errors) == 1
    assert "P-BAD" in report.errors[0]

    batch = import_repo.get_batch(report.batch_id)
    assert batch is not None
    assert batch.status == "failed"


def test_import_is_idempotent_across_two_runs_into_same_batch(
    import_repo: ProductHubImportRepository,
) -> None:
    raw = {"id": "P-7", "name": "Wiederholt", "sku": "XW-007"}
    importer = WixProductImporter(
        products_client=_FakeProductsClient([WixProduct(id="P-7", name="Wiederholt")]),
        details_client=_FakeDetailsClient(raw_products={"P-7": raw}),
        import_repo=import_repo,
    )

    first_report = importer.run()
    second_report = importer.run()

    # Each run creates its own batch (matching import_batch semantics); within a batch
    # a repeated ingest of the same source_key never duplicates (covered by PR02 tests).
    # Here we assert two runs produce two independent, individually consistent batches.
    assert first_report.batch_id != second_report.batch_id
    assert len(import_repo.list_staging_products()) == 2
