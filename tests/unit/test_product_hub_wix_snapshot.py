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

    def has_credentials(self) -> bool:
        return True

    def get_product_raw(self, product_id: str) -> dict[str, Any] | None:
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
            "id": "wix-1", "revision": "rev-1", "name": "Wix title", "description": "",
            "visible": True,
            "media": {"items": [
                {"id": "cover", "image": {"url": "https://cdn.example/cover.jpg"}},
                {"id": "inside", "image": {"url": "https://cdn.example/inside.jpg"}},
                {"id": "movie", "mediaType": "video", "url": "https://cdn.example/movie.mp4"},
            ]},
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


def test_snapshot_marks_removed_wix_image_stale_and_closes_converged_field_conflict(
    factory: sessionmaker[Session],
) -> None:
    products = ProductHubRepository(factory)
    product, _ = products.create_product(sku="XW-STALE", name="Same")
    products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id="wix-1"
    )
    wix = _FakeWix(
        {"id": "wix-1", "name": "Different", "visible": True, "media": {"items": [
            {"id": "cover", "image": {"url": "https://cdn.example/cover.jpg"}},
            {"id": "old", "image": {"url": "https://cdn.example/old.jpg"}},
        ]}}
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
