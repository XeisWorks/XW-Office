"""XW Product Hub — import staging schema (PR02).

Staging holds raw external data (Wix/sevdesk/Excel) so it can be reviewed and matched
against the canonical schema (``models/product_hub.py``) before anything is committed.
**No staging table ever writes to a canonical business table directly** — that only
happens through an explicit commit step (PR06), which is out of scope here.
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

IMPORT_SOURCES = ("wix", "sevdesk", "excel")
IMPORT_BATCH_STATUSES = ("pending", "running", "completed", "failed")

#: Mirrors docs/product_hub/XW_PRODUCT_HUB_CODEX_5_6_LUNA_BUILD_PLAN.md PR02 status model.
STAGING_MATCH_STATUSES = (
    "unmatched",
    "exact_match",
    "alias_match",
    "identifier_match",
    "suggested_match",
    "conflict",
    "approved",
    "rejected",
    "committed",
)
MATCH_METHODS = (
    "existing_external_id",
    "exact_sku",
    "sku_alias",
    "identifier",
    "fuzzy_suggested",
)


class ImportBatch(Base):
    """One run of "read products/variants/assets/stock from one source into staging"."""

    __tablename__ = "import_batch"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONVariant, default=dict, nullable=False
    )
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StagingProduct(Base):
    """One raw external product row, staged for review/matching.

    ``source_key`` is the stable natural key used for idempotent re-ingestion within a
    batch: the external product id for Wix/sevdesk, or a derived stable key (e.g.
    normalized SKU) for Excel rows that carry no external id. Re-ingesting the same
    ``(import_batch_id, source, source_key)`` updates the existing row in place rather
    than creating a duplicate — see ``ProductHubImportRepository.ingest_staging_product``.
    """

    __tablename__ = "staging_product"
    __table_args__ = (
        UniqueConstraint(
            "import_batch_id", "source", "source_key", name="uq_staging_product_batch_source_key"
        ),
        Index("ix_staging_product_match_status", "match_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_key: Mapped[str] = mapped_column(String(240), nullable=False)
    source_external_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONVariant, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_fields: Mapped[dict[str, object]] = mapped_column(
        JSONVariant, default=dict, nullable=False
    )
    proposed_product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    proposed_variant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    match_method: Mapped[str | None] = mapped_column(String(24), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched", nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    committed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    committed_product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class StagingVariant(Base):
    """One raw external variant row (e.g. a Wix Catalog V3 variant) under a staging product."""

    __tablename__ = "staging_variant"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    staging_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("staging_product.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_external_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    option_values: Mapped[dict[str, object]] = mapped_column(
        JSONVariant, default=dict, nullable=False
    )
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)
    proposed_variant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StagingIdentifier(Base):
    """One raw identifier (ISBN/ASIN/...) found for a staging product."""

    __tablename__ = "staging_identifier"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    staging_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("staging_product.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheme: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(180), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(180), nullable=False)
    conflict: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StagingAsset(Base):
    """One raw media/asset reference found for a staging product."""

    __tablename__ = "staging_asset"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    staging_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("staging_product.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    source_external_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StagingInventory(Base):
    """One raw stock reading (source-side quantity) for a staging product."""

    __tablename__ = "staging_inventory"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    staging_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("staging_product.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_external_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stock_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StagingCategory(Base):
    """One raw category reference found for a staging product."""

    __tablename__ = "staging_category"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    staging_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("staging_product.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_category_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    external_category_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ImportMatchCandidate(Base):
    """One ranked candidate match for a staging product (full list, for manual review).

    ``StagingProduct.proposed_product_id``/``match_method``/``match_score`` hold the
    single *best* candidate; this table holds every candidate considered (e.g. two
    plausible fuzzy-name matches), which the future review UI/command needs to let a
    human pick instead of the importer silently choosing one.
    """

    __tablename__ = "import_match_candidate"
    __table_args__ = (
        Index("ix_import_match_candidate_staging_product_rank", "staging_product_id", "rank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    staging_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("staging_product.id", ondelete="CASCADE"), nullable=False
    )
    candidate_product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    candidate_variant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    match_method: Mapped[str] = mapped_column(String(24), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    rank: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "JSONVariant",
    "IMPORT_SOURCES",
    "IMPORT_BATCH_STATUSES",
    "STAGING_MATCH_STATUSES",
    "MATCH_METHODS",
    "ImportBatch",
    "StagingProduct",
    "StagingVariant",
    "StagingIdentifier",
    "StagingAsset",
    "StagingInventory",
    "StagingCategory",
    "ImportMatchCandidate",
]
