"""Repository layer for the XW Product Hub import staging schema (PR02).

Nothing here ever writes to the canonical tables in ``models/product_hub.py`` — staging
is read/reviewed/matched first; committing staged rows into the canonical schema is a
separate, explicit step (PR06, ``import_commit_service``), out of scope here.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime
import hashlib
import json
import uuid
from collections.abc import Generator

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub_import import (
    ImportBatch,
    ImportMatchCandidate,
    StagingAsset,
    StagingCategory,
    StagingIdentifier,
    StagingInventory,
    StagingProduct,
    StagingVariant,
)


def hash_payload(payload: dict[str, object]) -> str:
    """Stable sha256 of a JSON-serializable payload, for idempotent re-import detection."""
    canonical = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StagingProductFilter:
    """Optional filters for :meth:`ProductHubImportRepository.list_staging_products`."""

    import_batch_id: uuid.UUID | None = None
    source: str | None = None
    match_status: str | None = None


class ProductHubImportRepository:
    """Data access for import batches and their staged rows."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    # -- batches ----------------------------------------------------------------

    def create_batch(
        self, *, source: str, source_metadata: dict[str, object] | None = None
    ) -> ImportBatch:
        with self._scope() as session:
            batch = ImportBatch(
                id=uuid.uuid4(),
                source=source,
                status="running",
                source_metadata=dict(source_metadata or {}),
            )
            session.add(batch)
            session.flush()
            return batch

    def finish_batch(
        self, batch_id: uuid.UUID, *, status: str, error_summary: str = ""
    ) -> ImportBatch:
        with self._scope() as session:
            batch = session.get(ImportBatch, batch_id)
            if batch is None:
                raise KeyError(f"Import batch {batch_id} not found")
            batch.status = status
            batch.error_summary = error_summary or None
            batch.finished_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return batch

    def get_batch(self, batch_id: uuid.UUID) -> ImportBatch | None:
        with self._scope() as session:
            return session.get(ImportBatch, batch_id)

    def set_batch_metadata(
        self, batch_id: uuid.UUID, source_metadata: dict[str, object]
    ) -> ImportBatch:
        """Replace ``source_metadata`` on a batch (caller merges, this just writes)."""
        with self._scope() as session:
            batch = session.get(ImportBatch, batch_id)
            if batch is None:
                raise KeyError(f"Import batch {batch_id} not found")
            batch.source_metadata = source_metadata
            session.flush()
            return batch

    # -- staging products ---------------------------------------------------------

    def ingest_staging_product(
        self,
        *,
        import_batch_id: uuid.UUID,
        source: str,
        source_key: str,
        raw_payload: dict[str, object],
        source_external_id: str = "",
        sku: str = "",
        name: str = "",
        normalized_fields: dict[str, object] | None = None,
    ) -> StagingProduct:
        """Insert or, for a repeated ``(batch, source, source_key)``, update in place.

        Idempotent within a batch: re-ingesting the same source row (e.g. a retried
        Wix page fetch) never creates a duplicate ``staging_product`` row. Any existing
        match decision (``match_status`` etc.) is left untouched — only the raw/derived
        fields are refreshed.
        """
        clean_key = str(source_key or "").strip()
        if not clean_key:
            raise ValueError("source_key is required")
        payload_hash = hash_payload(raw_payload)
        with self._scope() as session:
            existing = session.scalar(
                select(StagingProduct).where(
                    StagingProduct.import_batch_id == import_batch_id,
                    StagingProduct.source == source,
                    StagingProduct.source_key == clean_key,
                )
            )
            if existing is not None:
                existing.raw_payload = raw_payload
                existing.payload_hash = payload_hash
                existing.normalized_fields = dict(normalized_fields or {})
                existing.source_external_id = source_external_id or existing.source_external_id
                existing.sku = sku or existing.sku
                existing.name = name or existing.name
                session.flush()
                return existing

            staging_product = StagingProduct(
                id=uuid.uuid4(),
                import_batch_id=import_batch_id,
                source=source,
                source_key=clean_key,
                source_external_id=source_external_id or None,
                sku=sku or None,
                name=name or None,
                raw_payload=raw_payload,
                payload_hash=payload_hash,
                normalized_fields=dict(normalized_fields or {}),
                match_status="unmatched",
            )
            session.add(staging_product)
            session.flush()
            return staging_product

    def get_staging_product(self, staging_product_id: uuid.UUID) -> StagingProduct | None:
        with self._scope() as session:
            return session.get(StagingProduct, staging_product_id)

    def list_staging_products(
        self, filters: StagingProductFilter | None = None
    ) -> list[StagingProduct]:
        filters = filters or StagingProductFilter()
        with self._scope() as session:
            stmt = select(StagingProduct)
            if filters.import_batch_id is not None:
                stmt = stmt.where(StagingProduct.import_batch_id == filters.import_batch_id)
            if filters.source is not None:
                stmt = stmt.where(StagingProduct.source == filters.source)
            if filters.match_status is not None:
                stmt = stmt.where(StagingProduct.match_status == filters.match_status)
            stmt = stmt.order_by(StagingProduct.imported_at)
            return list(session.scalars(stmt).all())

    def set_match(
        self,
        staging_product_id: uuid.UUID,
        *,
        match_status: str,
        proposed_product_id: uuid.UUID | None = None,
        proposed_variant_id: uuid.UUID | None = None,
        match_method: str | None = None,
        match_score: float | None = None,
        decision_note: str = "",
    ) -> StagingProduct:
        with self._scope() as session:
            staging_product = session.get(StagingProduct, staging_product_id)
            if staging_product is None:
                raise KeyError(f"Staging product {staging_product_id} not found")
            staging_product.match_status = match_status
            staging_product.proposed_product_id = proposed_product_id
            staging_product.proposed_variant_id = proposed_variant_id
            staging_product.match_method = match_method
            staging_product.match_score = match_score
            staging_product.decision_note = decision_note or None
            session.flush()
            return staging_product

    def mark_committed(self, staging_product_id: uuid.UUID, *, product_id: uuid.UUID) -> StagingProduct:
        """Idempotency anchor for the PR06 commit service: records which canonical
        product a staging row became, so re-running a commit is a safe no-op."""
        with self._scope() as session:
            staging_product = session.get(StagingProduct, staging_product_id)
            if staging_product is None:
                raise KeyError(f"Staging product {staging_product_id} not found")
            staging_product.match_status = "committed"
            staging_product.committed_at = datetime.datetime.now(datetime.timezone.utc)
            staging_product.committed_product_id = product_id
            session.flush()
            return staging_product

    def merge_normalized_fields(
        self, staging_product_id: uuid.UUID, updates: dict[str, object]
    ) -> StagingProduct:
        """Shallow-merge *updates* into an existing staging_product's ``normalized_fields``.

        Used when a later source row (e.g. the Amazon sheet) adds identifiers/tags for
        a product an earlier row (e.g. the Produktpalette sheet) already staged in the
        same batch, without clobbering what that first ingest already recorded — unlike
        ``ingest_staging_product``, which replaces ``normalized_fields`` wholesale.
        """
        with self._scope() as session:
            staging_product = session.get(StagingProduct, staging_product_id)
            if staging_product is None:
                raise KeyError(f"Staging product {staging_product_id} not found")
            merged = dict(staging_product.normalized_fields)
            merged.update(updates)
            staging_product.normalized_fields = merged
            session.flush()
            return staging_product

    # -- staging sub-rows ---------------------------------------------------------

    def add_identifier(
        self,
        staging_product_id: uuid.UUID,
        *,
        scheme: str,
        value: str,
        normalized_value: str,
        conflict: bool = False,
    ) -> StagingIdentifier:
        with self._scope() as session:
            row = StagingIdentifier(
                id=uuid.uuid4(),
                staging_product_id=staging_product_id,
                scheme=scheme,
                value=value,
                normalized_value=normalized_value,
                conflict=conflict,
            )
            session.add(row)
            session.flush()
            return row

    def add_asset(
        self,
        staging_product_id: uuid.UUID,
        *,
        role: str,
        source_external_id: str = "",
        source_url: str = "",
        sort_order: int = 0,
    ) -> StagingAsset:
        with self._scope() as session:
            row = StagingAsset(
                id=uuid.uuid4(),
                staging_product_id=staging_product_id,
                role=role,
                source_external_id=source_external_id or None,
                source_url=source_url or None,
                sort_order=sort_order,
            )
            session.add(row)
            session.flush()
            return row

    def add_inventory(
        self,
        staging_product_id: uuid.UUID,
        *,
        quantity: int,
        location_external_id: str = "",
        stock_enabled: bool = True,
    ) -> StagingInventory:
        with self._scope() as session:
            row = StagingInventory(
                id=uuid.uuid4(),
                staging_product_id=staging_product_id,
                location_external_id=location_external_id or None,
                quantity=quantity,
                stock_enabled=stock_enabled,
            )
            session.add(row)
            session.flush()
            return row

    def add_category(
        self,
        staging_product_id: uuid.UUID,
        *,
        external_category_id: str = "",
        external_category_name: str = "",
    ) -> StagingCategory:
        with self._scope() as session:
            row = StagingCategory(
                id=uuid.uuid4(),
                staging_product_id=staging_product_id,
                external_category_id=external_category_id or None,
                external_category_name=external_category_name or None,
            )
            session.add(row)
            session.flush()
            return row

    def add_variant(
        self,
        staging_product_id: uuid.UUID,
        *,
        sku: str = "",
        name: str = "",
        source_external_id: str = "",
        option_values: dict[str, object] | None = None,
        raw_payload: dict[str, object] | None = None,
    ) -> StagingVariant:
        with self._scope() as session:
            row = StagingVariant(
                id=uuid.uuid4(),
                staging_product_id=staging_product_id,
                sku=sku or None,
                name=name or None,
                source_external_id=source_external_id or None,
                option_values=dict(option_values or {}),
                raw_payload=dict(raw_payload or {}),
            )
            session.add(row)
            session.flush()
            return row

    def list_identifiers(self, staging_product_id: uuid.UUID) -> list[StagingIdentifier]:
        with self._scope() as session:
            stmt = select(StagingIdentifier).where(
                StagingIdentifier.staging_product_id == staging_product_id
            )
            return list(session.scalars(stmt).all())

    def list_variants(self, staging_product_id: uuid.UUID) -> list[StagingVariant]:
        with self._scope() as session:
            stmt = select(StagingVariant).where(
                StagingVariant.staging_product_id == staging_product_id
            )
            return list(session.scalars(stmt).all())

    def list_categories(self, staging_product_id: uuid.UUID) -> list[StagingCategory]:
        with self._scope() as session:
            stmt = select(StagingCategory).where(
                StagingCategory.staging_product_id == staging_product_id
            )
            return list(session.scalars(stmt).all())

    def list_assets(self, staging_product_id: uuid.UUID) -> list[StagingAsset]:
        with self._scope() as session:
            stmt = (
                select(StagingAsset)
                .where(StagingAsset.staging_product_id == staging_product_id)
                .order_by(StagingAsset.sort_order)
            )
            return list(session.scalars(stmt).all())

    def list_inventory(self, staging_product_id: uuid.UUID) -> list[StagingInventory]:
        with self._scope() as session:
            stmt = select(StagingInventory).where(
                StagingInventory.staging_product_id == staging_product_id
            )
            return list(session.scalars(stmt).all())

    # -- match candidates -----------------------------------------------------------

    def add_match_candidate(
        self,
        staging_product_id: uuid.UUID,
        *,
        candidate_product_id: uuid.UUID,
        match_method: str,
        rank: int,
        candidate_variant_id: uuid.UUID | None = None,
        match_score: float | None = None,
    ) -> ImportMatchCandidate:
        with self._scope() as session:
            row = ImportMatchCandidate(
                id=uuid.uuid4(),
                staging_product_id=staging_product_id,
                candidate_product_id=candidate_product_id,
                candidate_variant_id=candidate_variant_id,
                match_method=match_method,
                match_score=match_score,
                rank=rank,
            )
            session.add(row)
            session.flush()
            return row

    def list_match_candidates(self, staging_product_id: uuid.UUID) -> list[ImportMatchCandidate]:
        with self._scope() as session:
            stmt = (
                select(ImportMatchCandidate)
                .where(ImportMatchCandidate.staging_product_id == staging_product_id)
                .order_by(ImportMatchCandidate.rank)
            )
            return list(session.scalars(stmt).all())
