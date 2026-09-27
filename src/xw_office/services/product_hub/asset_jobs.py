"""Durable private sample-page rendering backed by the existing outbox worker."""
from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import ProductAsset
from xw_office.models.product_hub_sync import OutboxEvent, ProductAssetJob
from xw_office.repositories.product_hub_sync import append_outbox_event
from xw_office.services.layout.sample_pages_models import SamplePageExportSettings, SamplePageJob
from xw_office.services.layout.sample_pages_service import SamplePageExportService
from xw_office.services.product_hub.onedrive import OneDriveAssetClient
from xw_office.services.product_hub.r2_storage import R2Storage

RENDERER_VERSION = "sample-pages-v1"


class AssetJobError(ValueError):
    pass


def _private_source_ids(asset: ProductAsset) -> tuple[str, str]:
    if asset.storage_kind != "ONEDRIVE" or not asset.source_external_id:
        raise AssetJobError("Sample pages require a private OneDrive source asset")
    drive_id, separator, item_id = asset.source_external_id.partition(":")
    if not separator or not drive_id or not item_id:
        raise AssetJobError("The OneDrive source reference is invalid")
    return drive_id, item_id


class ProductAssetJobService:
    """Enqueue and run retry-safe sample-page jobs.

    Rendering always occurs in a temporary directory. The persistent state is the
    database recipe/status plus private R2 output; neither source PDFs nor temporary
    JPGs remain on the Railway filesystem.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _recipe(*, pages: list[int], watermarked_pages: list[int], watermark_asset_id: uuid.UUID | None) -> dict[str, object]:
        regular = sorted(set(pages))
        watermarked = sorted(set(watermarked_pages))
        if not regular and not watermarked:
            raise AssetJobError("At least one page must be selected")
        if any(page < 1 for page in [*regular, *watermarked]):
            raise AssetJobError("Page numbers start at 1")
        if set(regular).intersection(watermarked):
            raise AssetJobError("A page cannot be regular and watermarked at the same time")
        if watermarked and watermark_asset_id is None:
            raise AssetJobError("Watermarked pages require a private watermark asset")
        return {
            "renderer_version": RENDERER_VERSION,
            "target_height_px": 1000,
            "max_size_kb": 200,
            "pages": regular,
            "watermarked_pages": watermarked,
            "watermark_asset_id": str(watermark_asset_id) if watermark_asset_id else "",
        }

    def enqueue(
        self,
        *,
        product_id: uuid.UUID,
        source_asset_id: uuid.UUID,
        pages: list[int],
        watermarked_pages: list[int] | None = None,
        watermark_asset_id: uuid.UUID | None = None,
        variant_id: uuid.UUID | None = None,
    ) -> ProductAssetJob:
        recipe = self._recipe(
            pages=pages,
            watermarked_pages=watermarked_pages or [],
            watermark_asset_id=watermark_asset_id,
        )
        with session_scope(self._session_factory) as session:
            source = session.get(ProductAsset, source_asset_id)
            if source is None or source.product_id != product_id:
                raise KeyError("Source asset not found for this product")
            _private_source_ids(source)
            if variant_id is not None:
                from xw_office.models.product_hub import ProductVariant
                variant = session.get(ProductVariant, variant_id)
                if variant is None or variant.product_id != product_id:
                    raise AssetJobError("Variant does not belong to this product")
            payload = {"product_id": str(product_id), "source": source.source_external_id,
                       "source_version": source.source_version or "", "recipe": recipe,
                       "variant_id": str(variant_id) if variant_id else ""}
            job_key = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            existing = session.scalar(select(ProductAssetJob).where(ProductAssetJob.job_key == job_key))
            if existing is not None:
                return existing
            job = ProductAssetJob(id=uuid.uuid4(), product_id=product_id, source_asset_id=source_asset_id,
                                  variant_id=variant_id, job_key=job_key, recipe=recipe, status="queued")
            session.add(job)
            session.flush()
            append_outbox_event(session, aggregate_type="product_asset_job", aggregate_id=job.id,
                                event_type="product.asset_render_requested", payload={"asset_job_id": str(job.id)})
            return job

    def get(self, job_id: uuid.UUID) -> ProductAssetJob | None:
        with session_scope(self._session_factory) as session:
            return session.get(ProductAssetJob, job_id)

    def run(self, event: OutboxEvent) -> None:
        job_id = uuid.UUID(str(event.payload["asset_job_id"]))
        with session_scope(self._session_factory) as session:
            job = session.get(ProductAssetJob, job_id)
            if job is None:
                raise KeyError("Asset job not found")
            if job.status == "succeeded":
                return
            job.status = "running"
            job.last_error = None
        try:
            manifest = self._render(job_id)
        except Exception as exc:
            with session_scope(self._session_factory) as session:
                job = session.get(ProductAssetJob, job_id)
                if job is not None:
                    job.status = "failed"
                    job.last_error = str(exc)[:4000]
            raise
        with session_scope(self._session_factory) as session:
            job = session.get(ProductAssetJob, job_id)
            if job is None:
                raise KeyError("Asset job not found")
            job.status = "succeeded"
            job.output_manifest = manifest
            job.last_error = None

    def _render(self, job_id: uuid.UUID) -> list[dict[str, object]]:
        with session_scope(self._session_factory) as session:
            job = session.get(ProductAssetJob, job_id)
            if job is None:
                raise KeyError("Asset job not found")
            source = session.get(ProductAsset, job.source_asset_id)
            if source is None:
                raise AssetJobError("Source asset was deleted")
            drive_id, item_id = _private_source_ids(source)
            recipe = dict(job.recipe)
            product_id, variant_id = job.product_id, job.variant_id
        graph = OneDriveAssetClient.from_environment()
        graph.assert_within_root(drive_id, item_id)
        pdf_bytes = graph.download(drive_id, item_id)
        storage = R2Storage.from_environment()
        with tempfile.TemporaryDirectory(prefix="xw-sample-pages-") as directory:
            work_dir = Path(directory)
            source_path = work_dir / "source.pdf"
            source_path.write_bytes(pdf_bytes)
            watermark_path: Path | None = None
            watermark_raw = str(recipe.get("watermark_asset_id") or "")
            if watermark_raw:
                with session_scope(self._session_factory) as session:
                    watermark = session.get(ProductAsset, uuid.UUID(watermark_raw))
                    if watermark is None or watermark.product_id != product_id:
                        raise AssetJobError("Watermark asset not found for this product")
                    watermark_drive, watermark_item = _private_source_ids(watermark)
                graph.assert_within_root(watermark_drive, watermark_item)
                watermark_path = work_dir / "watermark.png"
                watermark_path.write_bytes(graph.download(watermark_drive, watermark_item))
            results = SamplePageExportService().export(
                [SamplePageJob(source_path, tuple(recipe["pages"]), tuple(recipe["watermarked_pages"]))],
                SamplePageExportSettings(output_folder=work_dir / "out", target_height_px=int(recipe["target_height_px"]),
                                         max_size_kb=int(recipe["max_size_kb"]), watermark_path=watermark_path),
            )
            manifest: list[dict[str, object]] = []
            for result in results:
                marker = f"{result.page_number}-{'watermarked' if result.is_watermarked else 'regular'}"
                object_key = f"product-assets/{product_id}/{job_id}/{marker}.jpg"
                content = result.output_path.read_bytes()
                uri = storage.put_private(key=object_key, content=content, content_type="image/jpeg")
                external_id = f"{job_id}:{marker}"
                with session_scope(self._session_factory) as session:
                    existing = session.scalar(select(ProductAsset).where(
                        ProductAsset.source_channel == "sample-page-render",
                        ProductAsset.source_external_id == external_id,
                    ))
                    if existing is None:
                        asset = ProductAsset(id=uuid.uuid4(), product_id=product_id, variant_id=variant_id,
                            role="SAMPLE_SCORE", storage_kind="OBJECT_STORAGE", uri=uri,
                            original_filename=result.output_path.name, mime_type="image/jpeg", size_bytes=len(content),
                            checksum_sha256=hashlib.sha256(content).hexdigest(), source_channel="sample-page-render",
                            source_external_id=external_id, source_version=RENDERER_VERSION,
                            public_share_allowed=False, health_status="ok")
                        session.add(asset)
                    else:
                        asset = existing
                manifest.append({"asset_id": str(asset.id), "page_number": result.page_number,
                                 "watermarked": result.is_watermarked, "uri": uri,
                                 "size_bytes": len(content)})
            return manifest
