"""XW Product Hub — canonical product/variant/inventory/sync ORM models.

Schema per docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml. These tables are additive:
the legacy ``product`` table (migration 002/003) keeps its existing columns and gains
new ones here; ``product.sku``, ``wix_product_id``, ``sevdesk_part_id``, ``print_file_path``,
``min_stock_target`` and ``reprint_batch_qty`` remain as deprecated compatibility mirrors
until PR16 removes them once every consumer reads from the new tables instead.

"One default variant per product" is enforced by the repository layer
(``ProductHubRepository.set_default_variant``), not by a DB constraint here — a
dialect-portable partial unique index only exists in the PostgreSQL migration, since
SQLAlchemy's ``postgresql_where`` index option is ignored (not translated) on SQLite,
which the test suite uses for ``Base.metadata.create_all``.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
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

#: Flexible/free-form JSON payloads — JSONB on PostgreSQL, plain JSON elsewhere (SQLite tests).
JSONVariant = JSON().with_variant(JSONB(), "postgresql")

#: Reference values only — not enforced as DB constraints (matches this repo's existing
#: convention of plain ``String`` status columns, see ``product.status``,
#: ``CustomerAftercareCase.status``).
PRODUCT_STATUSES = ("draft", "review", "live", "archived")
PRODUCT_TYPES = ("physical", "digital", "hybrid")
IDENTIFIER_SCHEMES = (
    "ISBN13",
    "ISBN10",
    "EAN",
    "UPC",
    "ASIN",
    "FNSKU",
    "BARCODE",
    "LEGACY_SKU",
    "VLB_ID",
    "CUSTOM",
)
ASSET_ROLES = ("COVER", "SAMPLE_SCORE", "PRINT_PDF", "PREVIEW_PDF", "AUDIO", "DOWNLOAD", "OTHER")
ASSET_STORAGE_KINDS = ("OBJECT_STORAGE", "NETWORK_PATH", "WIX_MEDIA", "EXTERNAL_URL")
ASSET_HEALTH_STATUSES = ("unknown", "ok", "missing", "unreadable", "checksum_mismatch", "stale")
IMPROVEMENT_STATUSES = ("open", "planned", "resolved", "wont_fix")
IMPROVEMENT_SEVERITIES = ("info", "minor", "major", "critical")
CHANNEL_CODES = ("wix", "sevdesk", "amazon", "vlb")
SYNC_STATUSES = ("never", "pending", "synced", "conflict", "error", "disabled")


class Product(Base):
    """Canonical parent product — first ORM mapping of the ``product`` table.

    The table itself was created by migration 002/003 without a corresponding model
    (legacy code reads/writes it exclusively as ``SettingKV["inventory.products"]`` JSON,
    never through this table). Columns above the first blank line below are the original
    002/003 columns and must keep matching production exactly; columns below it are the
    additive PR01 columns. ``sku``, ``wix_product_id``, ``sevdesk_part_id``,
    ``print_file_path``, ``min_stock_target`` and ``reprint_batch_qty`` stay as deprecated
    compatibility mirrors of the new ``product_variant``/``channel_mapping``/``product_asset``/
    ``print_rule`` rows until PR16.
    """

    __tablename__ = "product"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_digital: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sevdesk_part_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    wix_product_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    print_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_stock_target: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    reprint_batch_qty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    brand_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    brand_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # -- PR01 additions (docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml `product`) --
    slug: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    short_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_family.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_type: Mapped[str] = mapped_column(String(16), default="physical", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    release_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    attributes: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    archived_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProductSkuAlias(Base):
    """Legacy/alternate SKU resolving to a product — bridged onto ``product_variant``.

    Maps the existing ``product_sku_alias`` table (migration 002). ``variant_id`` is the
    PR01 bridge column: nullable for now since historic aliases only carry ``product_id``;
    newly created aliases should set both.
    """

    __tablename__ = "product_sku_alias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias_sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="SET NULL"), nullable=True, index=True
    )


class ProductFamily(Base):
    """Template/group of common product attributes and readiness rules."""

    __tablename__ = "product_family"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    attribute_schema: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)
    readiness_rules: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProductVariant(Base):
    """Sellable/inventory-relevant SKU entity; every product has >= 1 variant."""

    __tablename__ = "product_variant"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    stock_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    weight_grams: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    option_values: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)
    attributes: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProductIdentifier(Base):
    """ISBN/ASIN/FNSKU/EAN/etc. attached to a product or a variant (never both)."""

    __tablename__ = "product_identifier"
    __table_args__ = (
        UniqueConstraint("scheme", "normalized_value", name="uq_product_identifier_scheme_value"),
        # Dialect-portable "exactly one owner" check (avoids PostgreSQL-only ``::int`` casts
        # so SQLite-backed tests via ``Base.metadata.create_all`` also enforce it).
        CheckConstraint(
            "(product_id IS NULL) != (variant_id IS NULL)",
            name="ck_product_identifier_exactly_one_owner",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product.id", ondelete="CASCADE"), nullable=True, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scheme: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(180), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(180), nullable=False)
    market: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Category(Base):
    """Internal hierarchical taxonomy, independent from Wix/sevdesk categories."""

    __tablename__ = "category"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("category.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ProductCategory(Base):
    """Many-to-many internal category assignment."""

    __tablename__ = "product_category"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("category.id", ondelete="RESTRICT"), primary_key=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Tag(Base):
    """Flexible cross-cutting label such as B2B/POD/VLB."""

    __tablename__ = "tag"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProductTag(Base):
    """Many-to-many product/tag assignment."""

    __tablename__ = "product_tag"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )


class PriceList(Base):
    """Named commercial context (RETAIL_EUR, B2B_EUR, later dealer-specific lists)."""

    __tablename__ = "price_list"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    customer_scope: Mapped[str] = mapped_column(String(40), default="retail", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rules: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)


class ProductPrice(Base):
    """Effective-dated variant price within a named price list."""

    __tablename__ = "product_price"
    __table_args__ = (
        Index(
            "ix_product_price_variant_list_valid_from",
            "variant_id",
            "price_list_id",
            "valid_from",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="CASCADE"), nullable=False
    )
    price_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("price_list.id", ondelete="RESTRICT"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    valid_from: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProductAsset(Base):
    """Media/production asset with explicit role and provenance.

    ``PRINT_PDF`` assets always use ``storage_kind='NETWORK_PATH'`` and
    ``public_share_allowed=False`` — the WebUI exposes metadata/health only, never a
    download/stream endpoint (confirmed architecture decision, see docs/product_hub/).
    """

    __tablename__ = "product_asset"
    __table_args__ = (
        Index("ix_product_asset_product_role_sort", "product_id", "role", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="CASCADE"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_share_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    health_status: Mapped[str] = mapped_column(
        String(20), default="unknown", nullable=False, index=True
    )
    last_checked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PrintRule(Base):
    """Canonical print/reprint policy per variant."""

    __tablename__ = "print_rule"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    min_stock_target: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    reprint_batch_qty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    print_profile_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    print_plan: Mapped[list[object]] = mapped_column(JSONVariant, default=list, nullable=False)
    primary_print_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_asset.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProductEdition(Base):
    """Print edition/revision of a publication."""

    __tablename__ = "product_edition"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    edition_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    published_at: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    print_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_asset.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProductImprovement(Base):
    """Persistent user/customer correction and improvement backlog item.

    Deliberately relational (one row per issue) rather than a single overwritten text
    field, so history survives and a new edition can pull in every open item.
    """

    __tablename__ = "product_improvement"
    __table_args__ = (
        Index("ix_product_improvement_product_status", "product_id", "status"),
        Index("ix_product_improvement_severity_status", "severity", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product.id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="RESTRICT"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(60), default="internal", nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="minor", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_in_edition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_edition.id", ondelete="SET NULL"), nullable=True
    )


class ChannelMapping(Base):
    """Stable relation between an internal entity and an external channel object."""

    __tablename__ = "channel_mapping"
    __table_args__ = (
        UniqueConstraint(
            "channel", "entity_type", "external_id", name="uq_channel_mapping_external"
        ),
        UniqueConstraint(
            "channel", "entity_type", "internal_entity_id", name="uq_channel_mapping_internal"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    internal_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    external_parent_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    external_revision: Mapped[str | None] = mapped_column(String(240), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(20), default="never", nullable=False)
    last_pulled_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_pushed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_external_updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChannelCategoryMapping(Base):
    """Maps internal taxonomy to Wix/sevdesk categories without conflating tags."""

    __tablename__ = "channel_category_mapping"
    __table_args__ = (
        UniqueConstraint(
            "category_id",
            "channel",
            "external_category_id",
            name="uq_channel_category_mapping",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("category.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    external_category_id: Mapped[str] = mapped_column(String(240), nullable=False)
    external_category_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AuditLog(Base):
    """Field-level application audit, separate from raw external payload archives."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity_created", "entity_type", "entity_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    changed_fields: Mapped[list[object]] = mapped_column(JSONVariant, default=list, nullable=False)
    before_data: Mapped[dict[str, object] | None] = mapped_column(JSONVariant, nullable=True)
    after_data: Mapped[dict[str, object] | None] = mapped_column(JSONVariant, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "JSONVariant",
    "PRODUCT_STATUSES",
    "PRODUCT_TYPES",
    "IDENTIFIER_SCHEMES",
    "ASSET_ROLES",
    "ASSET_STORAGE_KINDS",
    "ASSET_HEALTH_STATUSES",
    "IMPROVEMENT_STATUSES",
    "IMPROVEMENT_SEVERITIES",
    "CHANNEL_CODES",
    "SYNC_STATUSES",
    "Product",
    "ProductSkuAlias",
    "ProductFamily",
    "ProductVariant",
    "ProductIdentifier",
    "Category",
    "ProductCategory",
    "Tag",
    "ProductTag",
    "PriceList",
    "ProductPrice",
    "ProductAsset",
    "PrintRule",
    "ProductEdition",
    "ProductImprovement",
    "ChannelMapping",
    "ChannelCategoryMapping",
    "AuditLog",
]
