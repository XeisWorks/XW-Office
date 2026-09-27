from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub_sync import OutboxEvent
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.asset_jobs import AssetJobError, ProductAssetJobService
from xw_office.services.product_hub.r2_storage import R2Storage


def _factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'asset-jobs.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _source_asset(factory):
    product, _ = ProductHubRepository(factory).create_product(sku="XW-JOB", name="Asset Job")
    source = ProductHubRepository(factory).add_asset(
        product_id=product.id, role="PRINT_PDF", storage_kind="ONEDRIVE", uri="onedrive://drive/item",
        source_channel="onedrive", source_external_id="drive:item", source_version="etag-1",
    )
    return product, source


def test_sample_page_job_is_idempotent_for_same_source_version_and_recipe(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    product, source = _source_asset(factory)
    service = ProductAssetJobService(factory)

    first = service.enqueue(product_id=product.id, source_asset_id=source.id, pages=[3, 1, 3])
    second = service.enqueue(product_id=product.id, source_asset_id=source.id, pages=[1, 3])

    assert first.id == second.id
    with factory() as session:
        events = list(session.scalars(select(OutboxEvent)).all())
    assert len(events) == 1
    assert events[0].event_type == "product.asset_render_requested"


def test_sample_page_job_rejects_watermark_request_without_watermark_asset(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    product, source = _source_asset(factory)

    with pytest.raises(AssetJobError, match="Watermarked"):
        ProductAssetJobService(factory).enqueue(
            product_id=product.id, source_asset_id=source.id, pages=[], watermarked_pages=[1]
        )


def test_sample_page_job_requires_private_onedrive_source(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    product, _ = _source_asset(factory)
    other = ProductHubRepository(factory).add_asset(
        product_id=product.id, role="PRINT_PDF", storage_kind="OBJECT_STORAGE", uri="r2://bucket/score.pdf"
    )

    with pytest.raises(AssetJobError, match="OneDrive"):
        ProductAssetJobService(factory).enqueue(product_id=product.id, source_asset_id=other.id, pages=[1])


def test_private_r2_uri_cannot_escape_the_configured_bucket() -> None:
    storage = object.__new__(R2Storage)
    storage.bucket = "private-bucket"

    with pytest.raises(ValueError, match="configured private R2 bucket"):
        storage.get_private_uri("r2://other-bucket/object.jpg")
    with pytest.raises(ValueError, match="Invalid private R2 object key"):
        storage.get_private_uri("r2://private-bucket/a/../object.jpg")
