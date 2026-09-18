"""Read-only Wix source snapshots for mapped Product Hub products.

This is deliberately not an importer/matcher: only existing ``channel_mapping`` rows
are read.  It archives Wix product/variant/inventory source data, mirrors image
metadata, and feeds safe field differences into the conflict wizard's low-level
``sync_conflict`` ledger.  It never calls a Wix write endpoint and never downloads
image bytes.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.conflicts.normalizer import equivalent
from xw_office.services.product_hub.wix_import import _extract_media_items, _media_url

logger = logging.getLogger(__name__)


class WixSnapshotSource(Protocol):
    def get_product_raw(self, product_id: str) -> dict[str, Any] | None: ...

    def query_variants(self, product_id: str) -> list[dict[str, Any]]: ...

    def query_inventory(self, product_id: str) -> list[dict[str, Any]]: ...


@dataclass
class WixSnapshotReport:
    mappings_seen: int = 0
    products_fetched: int = 0
    payloads_archived: int = 0
    payloads_unchanged: int = 0
    images_created: int = 0
    images_updated: int = 0
    images_marked_stale: int = 0
    conflicts_created: int = 0
    conflicts_updated: int = 0
    conflicts_resolved: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "mappings_seen": self.mappings_seen,
            "products_fetched": self.products_fetched,
            "payloads_archived": self.payloads_archived,
            "payloads_unchanged": self.payloads_unchanged,
            "images_created": self.images_created,
            "images_updated": self.images_updated,
            "images_marked_stale": self.images_marked_stale,
            "conflicts_created": self.conflicts_created,
            "conflicts_updated": self.conflicts_updated,
            "conflicts_resolved": self.conflicts_resolved,
            "errors": list(self.errors),
        }


class WixSnapshotService:
    """Synchronise mapped Wix read models into the Hub's source/provenance records."""

    def __init__(self, factory: sessionmaker[Session], *, wix_client: WixSnapshotSource) -> None:
        self._products = ProductHubRepository(factory)
        self._sync = SyncRepository(factory)
        self._wix = wix_client

    def run(self) -> WixSnapshotReport:
        report = WixSnapshotReport()
        credential_check = getattr(self._wix, "has_credentials", None)
        if callable(credential_check) and not credential_check():
            report.errors.append("Wix credentials are not configured for the Product Hub service")
            return report
        mappings = self._products.list_channel_mappings_by_channel(channel="wix")
        report.mappings_seen = len(mappings)
        for mapping in mappings:
            try:
                self._snapshot_one(mapping.id, mapping.internal_entity_id, mapping.external_id, report)
            except Exception as exc:  # noqa: BLE001 - one remote object must not abort a scan
                logger.exception("Wix snapshot failed for %s", mapping.external_id)
                report.errors.append(f"{mapping.external_id}: {exc}")
        return report

    def _snapshot_one(
        self, mapping_id: uuid.UUID, product_id: uuid.UUID, external_id: str, report: WixSnapshotReport
    ) -> None:
        raw = self._wix.get_product_raw(external_id)
        if raw is None:
            raise RuntimeError("product detail fetch returned nothing")
        variants = self._wix.query_variants(external_id)
        inventory = self._wix.query_inventory(external_id)
        payload: dict[str, object] = {
            "product": raw,
            "variants": variants,
            "inventory": inventory,
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        _, archived = self._sync.archive_external_payload_if_changed(
            channel="wix", entity_type="product", external_id=external_id,
            payload=payload, payload_hash=payload_hash,
        )
        report.payloads_archived += int(archived)
        report.payloads_unchanged += int(not archived)
        self._products.record_channel_pull(
            mapping_id,
            external_revision=str(raw.get("revision") or raw.get("_revision") or "") or None,
            payload_hash=payload_hash,
            external_updated_at=_updated_at(raw),
        )
        created, updated, stale = self._products.sync_wix_image_assets(
            product_id, images=_image_assets(raw)
        )
        report.images_created += created
        report.images_updated += updated
        report.images_marked_stale += stale
        product = self._products.get_product(product_id)
        if product is None:
            raise RuntimeError(f"mapped Product Hub product {product_id} is missing")
        for field_name, hub_value, wix_value in _comparable_fields(product, raw):
            if equivalent(field_name, hub_value, wix_value):
                # The normalizer, not string equality, defines semantic convergence.
                wix_value = hub_value
            _, outcome = self._sync.upsert_scanned_conflict(
                channel="wix", entity_type="product", internal_entity_id=product_id,
                field_name=field_name, hub_value=hub_value, external_value=wix_value,
                external_updated_at=_updated_at(raw),
            )
            if outcome == "created":
                report.conflicts_created += 1
            elif outcome == "updated":
                report.conflicts_updated += 1
            elif outcome == "resolved":
                report.conflicts_resolved += 1
        report.products_fetched += 1


def _comparable_fields(product: Any, raw: dict[str, Any]) -> list[tuple[str, str, str]]:
    """The fields that already have safe Conflict-Wizard resolution semantics."""
    return [
        ("name", str(product.name or ""), str(raw.get("name") or "")),
        (
            "description",
            str(product.description or ""),
            str(raw.get("description") or raw.get("plainDescription") or ""),
        ),
        ("visible", "true" if product.active else "false", "true" if bool(raw.get("visible", True)) else "false"),
    ]


def _image_assets(raw: dict[str, Any]) -> list[dict[str, object]]:
    images: list[dict[str, object]] = []
    for item in _extract_media_items(raw):
        image = item.get("image")
        media_type = str(item.get("mediaType") or item.get("type") or "").lower()
        url = _media_url(item)
        if not url or (not isinstance(image, dict) and media_type not in {"image", "photo"}):
            continue
        external_id = str(item.get("id") or "").strip()
        if not external_id:
            external_id = "wix-media:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
        images.append(
            {
                "external_id": external_id,
                "url": url,
                "role": "COVER" if not images else "GALLERY_IMAGE",
                "sort_order": len(images),
            }
        )
    return images


def _updated_at(raw: dict[str, Any]) -> datetime.datetime | None:
    value = raw.get("lastUpdatedDate") or raw.get("updatedDate") or raw.get("updatedAt")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
