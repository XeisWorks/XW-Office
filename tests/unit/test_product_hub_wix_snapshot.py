"""Read-only Wix source snapshot tests, including product-image provenance."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.conflicts import ConflictWizardService
from xw_office.services.product_hub.wix_snapshot import WixSnapshotService


class _FakeWix:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.raw_calls = 0

    def has_credentials(self) -> bool:
        return True

    def get_product_raw(self, product_id: str) -> dict[str, Any] | None:
        self.raw_calls += 1
        return self.raw if product_id == "wix-1" else None

    def query_variants(self, product_id: str) -> list[dict[str, Any]]:
        return [{"id": "variant-1", "sku": "XW-SNAPSHOT"}]

    def query_inventory(self, product_id: str) -> list[dict[str, Any]]:
        return [{"variantId": "variant-1", "quantity": 4}]


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def test_snapshot_archives_mapped_wix_product_and_preserves_all_product_images(
    factory: sessionmaker[Session],
) -> None:
    products = ProductHubRepository(factory)
    product, _ = products.create_product(sku="XW-SNAPSHOT", name="Hub title")
    products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id="wix-1"
    )
    wix = _FakeWix(
        {
            "id": "wix-1",
            "revision": "rev-1",
            "name": "Wix title",
            "description": "",
            "visible": True,
            "media": {
                "items": [
                    {"id": "cover", "image": {"url": "https://cdn.example/cover.jpg"}},
                    {"id": "inside", "image": {"url": "https://cdn.example/inside.jpg"}},
                    {"id": "movie", "mediaType": "video", "url": "https://cdn.example/movie.mp4"},
                ]
            },
        }
    )
    service = WixSnapshotService(factory, wix_client=wix)

    first = service.run()
    second = service.run()

    assert first.products_fetched == 1
    assert first.payloads_archived == 1
    assert first.images_created == 2
    assert first.conflicts_created == 1
    assert second.payloads_unchanged == 1
    assert second.images_created == 0
    assert second.images_updated == 0
    assert len(SyncRepository(factory).list_open_sync_conflicts(channel="wix")) == 1
    assets = products.list_assets(product.id)
    assert [(row.role, row.source_external_id, row.uri) for row in assets] == [
        ("COVER", "cover", "https://cdn.example/cover.jpg"),
        ("GALLERY_IMAGE", "inside", "https://cdn.example/inside.jpg"),
    ]
    assert all(row.storage_kind == "WIX_MEDIA" for row in assets)

    cases = ConflictWizardService(factory).scan_low_level_conflicts()
    assert cases["cases_created"] == 1


def test_incremental_snapshot_uses_catalog_revision_to_skip_unchanged_details(
    factory: sessionmaker[Session],
) -> None:
    class _Catalog:
        def __init__(self) -> None:
            self.rows: list[dict[str, str]] = [{"id": "wix-1", "revision": "rev-1"}]
            self.calls = 0

        def list_products(self, *, include_hidden: bool = True) -> list[object]:
            self.calls += 1
            assert include_hidden is True
            return self.rows

    products = ProductHubRepository(factory)
    product, _ = products.create_product(sku="XW-CACHED", name="Hub title")
    products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id="wix-1"
    )
    wix = _FakeWix({"id": "wix-1", "revision": "rev-1", "name": "Hub title", "visible": True})
    catalog = _Catalog()
    service = WixSnapshotService(factory, wix_client=wix, wix_catalog_client=catalog)

    first = service.run(force=True)
    second = service.run()

    assert first.full_refresh is True
    assert first.products_fetched == 1
    assert second.catalog_products_indexed == 1
    assert second.products_fetched == 0
    assert second.products_cached == 1
    assert wix.raw_calls == 1

    catalog.rows = [{"id": "wix-1", "revision": "rev-2"}]
    wix.raw["revision"] = "rev-2"
    third = service.run()

    assert third.products_fetched == 1
    assert third.products_cached == 0
    assert wix.raw_calls == 2


def test_snapshot_marks_removed_wix_image_stale_and_closes_converged_field_conflict(
    factory: sessionmaker[Session],
) -> None:
    products = ProductHubRepository(factory)
    product, _ = products.create_product(sku="XW-STALE", name="Same")
    products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id="wix-1"
    )
    wix = _FakeWix(
        {
            "id": "wix-1",
            "name": "Different",
            "visible": True,
            "media": {
                "items": [
                    {"id": "cover", "image": {"url": "https://cdn.example/cover.jpg"}},
                    {"id": "old", "image": {"url": "https://cdn.example/old.jpg"}},
                ]
            },
        }
    )
    service = WixSnapshotService(factory, wix_client=wix)
    service.run()
    wix.raw["name"] = "Same"
    wix.raw["media"]["items"] = [wix.raw["media"]["items"][0]]

    report = service.run()

    assert report.images_marked_stale == 1
    assert report.conflicts_resolved == 1
    assert SyncRepository(factory).list_open_sync_conflicts(channel="wix") == []
    assert [row.health_status for row in products.list_assets(product.id)] == ["unknown", "stale"]


def test_snapshot_reports_missing_wix_credentials_once(factory: sessionmaker[Session]) -> None:
    class _NoCredentialsWix(_FakeWix):
        def has_credentials(self) -> bool:
            return False

    report = WixSnapshotService(factory, wix_client=_NoCredentialsWix({})).run()

    assert report.mappings_seen == 0
    assert report.errors == ["Wix credentials are not configured for the Product Hub service"]


def test_catalog_v1_snapshot_avoids_v3_variant_and_inventory_probes(
    factory: sessionmaker[Session],
) -> None:
    class _V1Wix(_FakeWix):
        def __init__(self) -> None:
            super().__init__({"id": "wix-1", "name": "Product", "visible": True})
            self.variant_calls = self.inventory_calls = 0

        def detect_catalog_version(self) -> str:
            return "v1"

        def query_variants(self, product_id: str) -> list[dict[str, Any]]:
            self.variant_calls += 1
            return super().query_variants(product_id)

        def query_inventory(self, product_id: str) -> list[dict[str, Any]]:
            self.inventory_calls += 1
            return super().query_inventory(product_id)

    products = ProductHubRepository(factory)
    product, _ = products.create_product(sku="XW-V1", name="Product")
    products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id="wix-1"
    )
    wix = _V1Wix()

    report = WixSnapshotService(factory, wix_client=wix).run()

    assert report.products_fetched == 1
    assert wix.variant_calls == 0
    assert wix.inventory_calls == 0


def test_missing_wix_object_creates_a_critical_mapping_case(
    factory: sessionmaker[Session],
) -> None:
    products = ProductHubRepository(factory)
    product, _ = products.create_product(sku="XW-MISSING-WIX", name="Missing Wix object")
    products.create_channel_mapping(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        external_id="wix-missing",
    )
    report = WixSnapshotService(factory, wix_client=_FakeWix({})).run()

    assert report.products_fetched == 0
    assert report.mapping_conflicts_created == 1
    low = SyncRepository(factory).list_open_sync_conflicts(channel="wix")
    assert len(low) == 1
    assert low[0].field_name == "mapping"
    assert low[0].external_value == {
        "external_id": "wix-missing",
        "state": "not_found",
        "error": "product detail fetch returned nothing",
    }
    scan = ConflictWizardService(factory).scan_low_level_conflicts()
    case = ConflictWizardService(factory).repository.list_cases()[0][0]
    assert scan["cases_created"] == 1
    assert case.conflict_type == "WRONG_PRODUCT_MAPPING"
    assert case.severity == "CRITICAL"


def test_variant_mapping_is_checked_via_its_wix_parent_and_detects_a_missing_variant(
    factory: sessionmaker[Session],
) -> None:
    products = ProductHubRepository(factory)
    product, variant = products.create_product(sku="XW-VARIANT", name="Variant product")
    products.create_channel_mapping(
        channel="wix",
        entity_type="variant",
        internal_entity_id=variant.id,
        external_id="wix-variant",
        external_parent_id="wix-1",
    )
    wix = _FakeWix(
        {
            "id": "wix-1",
            "name": "Variant product",
            "visible": True,
            "variants": [{"id": "wix-variant", "sku": "XW-VARIANT"}],
        }
    )

    first = WixSnapshotService(factory, wix_client=wix).run()
    assert first.products_fetched == 1
    assert first.mapping_conflicts_created == 0

    wix.raw["variants"] = []
    report = WixSnapshotService(factory, wix_client=wix).run()
    assert report.mapping_conflicts_created == 1
    low = SyncRepository(factory).list_open_sync_conflicts(channel="wix")
    assert low[0].entity_type == "variant"
    assert low[0].internal_entity_id == variant.id

    ConflictWizardService(factory).scan_low_level_conflicts()
    case = ConflictWizardService(factory).repository.list_cases()[0][0]
    assert case.product_id == product.id
    assert case.variant_id == variant.id
    assert case.title.startswith("XW-VARIANT")


def test_catalog_scan_surfaces_hub_product_without_wix_mapping_and_can_link_it(
    factory: sessionmaker[Session],
) -> None:
    class _Catalog:
        def list_products(self, *, include_hidden: bool = True) -> list[object]:
            assert include_hidden is True
            return [{"id": "wix-existing", "name": "Already in Wix", "sku": "XW-UNMAPPED"}]

    products = ProductHubRepository(factory)
    product, _ = products.create_product(sku="XW-UNMAPPED", name="Already in Wix")
    service = WixSnapshotService(
        factory,
        wix_client=_FakeWix({"id": "wix-1"}),
        wix_catalog_client=_Catalog(),
    )

    report = service.run()
    assert report.unmapped_hub_products == 1
    assert report.unmapped_mapping_conflicts_created == 1
    low = SyncRepository(factory).list_open_sync_conflicts(channel="wix")
    assert low[0].external_value == {"state": "unmapped", "sku": "XW-UNMAPPED"}

    wizard = ConflictWizardService(factory)
    wizard.scan_low_level_conflicts()
    case = wizard.repository.list_cases()[0][0]
    wizard.remap_wix_mapping(
        case.id, expected_row_version=case.row_version, external_id="wix-existing"
    )

    mappings = products.list_channel_mappings(entity_type="product", internal_entity_id=product.id)
    assert [(mapping.channel, mapping.external_id) for mapping in mappings] == [("wix", "wix-existing")]
