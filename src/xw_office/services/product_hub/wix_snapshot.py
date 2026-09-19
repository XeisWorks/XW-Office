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
from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.conflicts.normalizer import equivalent
from xw_office.services.product_hub.wix_import import _extract_media_items, _media_url
from xw_office.services.wix.identifiers import canonical_wix_id

logger = logging.getLogger(__name__)


class WixSnapshotSource(Protocol):
    def get_product_raw(self, product_id: str) -> dict[str, Any] | None: ...

    def query_variants(self, product_id: str) -> list[dict[str, Any]]: ...

    def query_inventory(self, product_id: str) -> list[dict[str, Any]]: ...


class WixCatalogIndexSource(Protocol):
    """Cheap paginated catalog index used to avoid per-product detail reads."""

    def list_products(self, *, include_hidden: bool = True) -> list[object]: ...


@dataclass
class WixSnapshotReport:
    mappings_seen: int = 0
    catalog_products_indexed: int = 0
    products_fetched: int = 0
    products_cached: int = 0
    products_missing_from_index: int = 0
    full_refresh: bool = False
    payloads_archived: int = 0
    payloads_unchanged: int = 0
    images_created: int = 0
    images_updated: int = 0
    images_marked_stale: int = 0
    conflicts_created: int = 0
    conflicts_updated: int = 0
    conflicts_resolved: int = 0
    mapping_conflicts_created: int = 0
    mapping_conflicts_updated: int = 0
    mapping_conflicts_resolved: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "mappings_seen": self.mappings_seen,
            "catalog_products_indexed": self.catalog_products_indexed,
            "products_fetched": self.products_fetched,
            "products_cached": self.products_cached,
            "products_missing_from_index": self.products_missing_from_index,
            "full_refresh": self.full_refresh,
            "payloads_archived": self.payloads_archived,
            "payloads_unchanged": self.payloads_unchanged,
            "images_created": self.images_created,
            "images_updated": self.images_updated,
            "images_marked_stale": self.images_marked_stale,
            "conflicts_created": self.conflicts_created,
            "conflicts_updated": self.conflicts_updated,
            "conflicts_resolved": self.conflicts_resolved,
            "mapping_conflicts_created": self.mapping_conflicts_created,
            "mapping_conflicts_updated": self.mapping_conflicts_updated,
            "mapping_conflicts_resolved": self.mapping_conflicts_resolved,
            "errors": list(self.errors),
        }


class WixSnapshotService:
    """Synchronise mapped Wix read models into the Hub's source/provenance records."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        wix_client: WixSnapshotSource,
        wix_catalog_client: WixCatalogIndexSource | None = None,
    ) -> None:
        self._products = ProductHubRepository(factory)
        self._sync = SyncRepository(factory)
        self._wix = wix_client
        self._catalog = wix_catalog_client

    def run(self, *, force: bool = False) -> WixSnapshotReport:
        report = WixSnapshotReport(full_refresh=force)
        credential_check = getattr(self._wix, "has_credentials", None)
        if callable(credential_check) and not credential_check():
            report.errors.append("Wix credentials are not configured for the Product Hub service")
            return report
        mappings = self._products.list_channel_mappings_by_channel(channel="wix")
        report.mappings_seen = len(mappings)
        catalog_index = self._load_catalog_index(mappings, report, force=force)
        for mapping in mappings:
            try:
                index_entry = (
                    catalog_index.get(_canonical_wix_id(mapping.external_id))
                    if catalog_index is not None
                    else None
                )
                if catalog_index is not None and index_entry is None:
                    report.products_missing_from_index += 1
                    # A partial index response must never turn a healthy mapping into
                    # a critical case. Confirm absence with the established detail
                    # endpoint, which is also how legacy/malformed IDs are diagnosed.
                    self._snapshot_one(
                        mapping.id, mapping.internal_entity_id, mapping.external_id, report
                    )
                    continue
                if (
                    index_entry is not None
                    and not force
                    and _mapping_is_current(mapping, index_entry)
                ):
                    report.products_cached += 1
                    self._record_mapping_healthy(
                        product_id=mapping.internal_entity_id,
                        external_id=mapping.external_id,
                        report=report,
                    )
                    continue
                self._snapshot_one(
                    mapping.id, mapping.internal_entity_id, mapping.external_id, report
                )
            except Exception as exc:  # noqa: BLE001 - one remote object must not abort a scan
                logger.exception("Wix snapshot failed for %s", mapping.external_id)
                report.errors.append(f"{mapping.external_id}: {exc}")
                self._record_mapping_failure(
                    product_id=mapping.internal_entity_id,
                    external_id=mapping.external_id,
                    error=str(exc),
                    report=report,
                )
        return report

    def _load_catalog_index(
        self, mappings: list[Any], report: WixSnapshotReport, *, force: bool
    ) -> dict[str, object] | None:
        """Return a current Wix index, or safely fall back to detail reads."""
        if force or self._catalog is None:
            return None
        try:
            rows = self._catalog.list_products(include_hidden=True)
        except Exception as exc:  # noqa: BLE001 - source scan stays best-effort
            logger.warning("Wix catalog index unavailable; falling back to detail reads: %s", exc)
            report.errors.append("Wix catalog index unavailable; used full detail fallback")
            return None
        index = {
            _canonical_wix_id(_index_value(row, "id")): row
            for row in rows
            if _index_value(row, "id")
        }
        report.catalog_products_indexed = len(index)
        if mappings and not index:
            report.errors.append("Wix catalog index was empty; used full detail fallback")
            return None
        return index

    def _snapshot_one(
        self,
        mapping_id: uuid.UUID,
        product_id: uuid.UUID,
        external_id: str,
        report: WixSnapshotReport,
    ) -> None:
        raw = self._wix.get_product_raw(external_id)
        if raw is None:
            failure_reader = getattr(self._wix, "get_last_product_raw_failure", None)
            failure = failure_reader() if callable(failure_reader) else None
            error = str((failure or {}).get("error") or "product detail fetch returned nothing")
            raise RuntimeError(error)
        self._record_mapping_healthy(product_id=product_id, external_id=external_id, report=report)
        # A Catalog V1 shop returns product details/media through its V1 product
        # endpoint, but has no compatible V3 variants/inventory query endpoints.
        # Avoid four guaranteed 404 probes per product; V1 stock/inline variants
        # remain part of the raw product payload and are therefore still archived.
        if _is_catalog_v1(self._wix):
            variants: list[dict[str, Any]] = []
            inventory: list[dict[str, Any]] = []
        else:
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
            channel="wix",
            entity_type="product",
            external_id=external_id,
            payload=payload,
            payload_hash=payload_hash,
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
                channel="wix",
                entity_type="product",
                internal_entity_id=product_id,
                field_name=field_name,
                hub_value=hub_value,
                external_value=wix_value,
                external_updated_at=_updated_at(raw),
            )
            if outcome == "created":
                report.conflicts_created += 1
            elif outcome == "updated":
                report.conflicts_updated += 1
            elif outcome == "resolved":
                report.conflicts_resolved += 1
        report.products_fetched += 1

    def _record_mapping_failure(
        self,
        *,
        product_id: uuid.UUID,
        external_id: str,
        error: str,
        report: WixSnapshotReport,
    ) -> None:
        expected = _mapping_state(external_id)
        failure_reader = getattr(self._wix, "get_last_product_raw_failure", None)
        failure = failure_reader() if callable(failure_reader) else None
        actual = {
            **expected,
            **(failure if isinstance(failure, dict) else {"state": "not_found"}),
            "error": error[:1000],
        }
        _, outcome = self._sync.upsert_scanned_conflict(
            channel="wix",
            entity_type="product",
            internal_entity_id=product_id,
            field_name="mapping",
            hub_value=expected,
            external_value=actual,
        )
        if outcome == "created":
            report.mapping_conflicts_created += 1
        elif outcome == "updated":
            report.mapping_conflicts_updated += 1

    def _record_mapping_healthy(
        self, *, product_id: uuid.UUID, external_id: str, report: WixSnapshotReport
    ) -> None:
        expected = _mapping_state(external_id)
        _, outcome = self._sync.upsert_scanned_conflict(
            channel="wix",
            entity_type="product",
            internal_entity_id=product_id,
            field_name="mapping",
            hub_value=expected,
            external_value=expected,
        )
        if outcome == "resolved":
            report.mapping_conflicts_resolved += 1


def _canonical_wix_id(value: object) -> str:
    """Normalise only for comparison; provenance retains the original external ID."""
    return canonical_wix_id(value)


def _index_value(row: object, key: str) -> object:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _mapping_is_current(mapping: Any, index_entry: object) -> bool:
    """Only skip a detail fetch when Wix supplied a trustworthy change marker."""
    remote_revision = str(_index_value(index_entry, "revision") or "").strip()
    local_revision = str(mapping.external_revision or "").strip()
    if remote_revision and local_revision:
        return remote_revision == local_revision

    remote_updated_at = _updated_at(
        {
            "lastUpdatedDate": _index_value(index_entry, "updated_at")
            or _index_value(index_entry, "lastUpdatedDate")
            or _index_value(index_entry, "updatedDate")
            or _index_value(index_entry, "updatedAt")
            or _index_value(index_entry, "_updatedDate"),
        }
    )
    local_updated_at = mapping.last_external_updated_at
    if remote_updated_at is None or local_updated_at is None:
        return False
    if local_updated_at.tzinfo is None:
        local_updated_at = local_updated_at.replace(tzinfo=datetime.timezone.utc)
    return remote_updated_at.astimezone(datetime.timezone.utc) == local_updated_at.astimezone(
        datetime.timezone.utc
    )


def _comparable_fields(product: Any, raw: dict[str, Any]) -> list[tuple[str, str, str]]:
    """The fields that already have safe Conflict-Wizard resolution semantics."""
    return [
        ("name", str(product.name or ""), str(raw.get("name") or "")),
        (
            "description",
            str(product.description or ""),
            str(raw.get("description") or raw.get("plainDescription") or ""),
        ),
        (
            "visible",
            "true" if product.active else "false",
            "true" if bool(raw.get("visible", True)) else "false",
        ),
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


def _is_catalog_v1(source: WixSnapshotSource) -> bool:
    """Detect V1 without coupling test doubles to Wix's concrete client type."""
    detect_version = getattr(source, "detect_catalog_version", None)
    if not callable(detect_version):
        return False
    version = detect_version()
    return str(getattr(version, "value", version)).lower() == "v1"


def _mapping_state(external_id: str) -> dict[str, str]:
    return {"external_id": external_id, "state": "mapped"}
