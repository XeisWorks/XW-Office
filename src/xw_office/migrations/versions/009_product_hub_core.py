"""XW Product Hub PR01: canonical product/variant/pricing/asset/sync schema.

Additive from the current head. Extends the existing ``product`` table (migration
002/003) with new columns and adds the full set of new tables described in
docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml — product_family, product_variant,
product_identifier, category(+product_category), tag(+product_tag), price_list,
product_price, product_asset, print_rule, product_edition, product_improvement,
channel_mapping, channel_category_mapping, audit_log — plus a ``variant_id`` bridge
column on the existing ``product_sku_alias`` table.

For every pre-existing ``product`` row this migration backfills exactly one default
``product_variant`` (SKU copied verbatim, normalized upper-case), mirrors
``wix_product_id``/``sevdesk_part_id`` into ``channel_mapping``, mirrors
``print_file_path`` into a ``product_asset`` (role=PRINT_PDF, storage_kind=NETWORK_PATH),
and mirrors ``min_stock_target``/``reprint_batch_qty`` into ``print_rule``. The legacy
``product`` columns are *not* removed — they stay as deprecated compatibility mirrors
until PR16 (see docs/product_hub/XW_PRODUCT_HUB_CODEX_5_6_LUNA_BUILD_PLAN.md PR01/PR16).

This migration does not write to Wix or sevdesk and does not touch
``SettingKV["inventory.products"]`` / ``inventory.stock_levels``.

Revision ID: 009_product_hub_core
Revises: 008_digital_license_fulfillment
Create Date: 2026-09-16

"""
from __future__ import annotations

import datetime
import re
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_product_hub_core"
down_revision: Union[str, Sequence[str], None] = "008_digital_license_fulfillment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    text = _SLUG_INVALID_CHARS.sub("-", text).strip("-")
    return text or "product"


def _uuid_pk() -> sa.Column[uuid.UUID]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _timestamps() -> list[sa.Column[datetime.datetime]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    is_fresh_product_hub = "product_variant" not in existing_tables

    # ------------------------------------------------------------------ #
    # product_family                                                       #
    # ------------------------------------------------------------------ #
    if "product_family" not in existing_tables:
        op.create_table(
            "product_family",
            _uuid_pk(),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column(
                "attribute_schema",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "readiness_rules",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            *_timestamps(),
        )
        op.create_index("ix_product_family_code", "product_family", ["code"], unique=True)

    # ------------------------------------------------------------------ #
    # product — additive columns                                          #
    # ------------------------------------------------------------------ #
    existing_product_columns = {c["name"] for c in inspector.get_columns("product")}

    if "slug" not in existing_product_columns:
        op.add_column("product", sa.Column("slug", sa.String(length=320), nullable=True))
    if "short_description" not in existing_product_columns:
        op.add_column("product", sa.Column("short_description", sa.Text(), nullable=True))
    if "description" not in existing_product_columns:
        op.add_column("product", sa.Column("description", sa.Text(), nullable=True))
    if "family_id" not in existing_product_columns:
        op.add_column(
            "product", sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True)
        )
        op.create_foreign_key(
            "fk_product_family_id",
            "product",
            "product_family",
            ["family_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_product_family_id", "product", ["family_id"])
    if "product_type" not in existing_product_columns:
        op.add_column(
            "product",
            sa.Column(
                "product_type",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'physical'"),
            ),
        )
    if "active" not in existing_product_columns:
        op.add_column(
            "product",
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index("ix_product_active", "product", ["active"])
    if "release_date" not in existing_product_columns:
        op.add_column("product", sa.Column("release_date", sa.Date(), nullable=True))
    if "attributes" not in existing_product_columns:
        op.add_column(
            "product",
            sa.Column(
                "attributes",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    if "row_version" not in existing_product_columns:
        op.add_column(
            "product",
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        )
    if "archived_at" not in existing_product_columns:
        op.add_column(
            "product", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
        )

    # ------------------------------------------------------------------ #
    # product_variant                                                      #
    # ------------------------------------------------------------------ #
    if "product_variant" not in existing_tables:
        op.create_table(
            "product_variant",
            _uuid_pk(),
            sa.Column(
                "product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("sku", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=300), nullable=True),
            sa.Column(
                "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "stock_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column("weight_grams", sa.Numeric(12, 3), nullable=True),
            sa.Column(
                "option_values",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "attributes",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            *_timestamps(),
        )
        op.create_index("ix_product_variant_sku", "product_variant", ["sku"], unique=True)
        op.create_index("ix_product_variant_product_id", "product_variant", ["product_id"])
        op.create_index("ix_product_variant_active", "product_variant", ["active"])
        # Partial unique index: at most one default variant per product. PostgreSQL-only
        # (SQLAlchemy's ``postgresql_where`` has no portable equivalent); the app layer
        # (``ProductHubRepository.set_default_variant``) enforces the same invariant on
        # every dialect, including the SQLite-backed test suite.
        op.create_index(
            "ix_product_variant_one_default_per_product",
            "product_variant",
            ["product_id"],
            unique=True,
            postgresql_where=sa.text("is_default = true"),
        )

    # ------------------------------------------------------------------ #
    # product_sku_alias — bridge to product_variant                        #
    # ------------------------------------------------------------------ #
    existing_alias_columns = {c["name"] for c in inspector.get_columns("product_sku_alias")}
    if "variant_id" not in existing_alias_columns:
        op.add_column(
            "product_sku_alias",
            sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_product_sku_alias_variant_id",
            "product_sku_alias",
            "product_variant",
            ["variant_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_product_sku_alias_variant_id", "product_sku_alias", ["variant_id"]
        )

    # ------------------------------------------------------------------ #
    # product_identifier                                                   #
    # ------------------------------------------------------------------ #
    if "product_identifier" not in existing_tables:
        op.create_table(
            "product_identifier",
            _uuid_pk(),
            sa.Column(
                "product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "variant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_variant.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("scheme", sa.String(length=20), nullable=False),
            sa.Column("value", sa.String(length=180), nullable=False),
            sa.Column("normalized_value", sa.String(length=180), nullable=False),
            sa.Column("market", sa.String(length=16), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source", sa.String(length=40), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "scheme", "normalized_value", name="uq_product_identifier_scheme_value"
            ),
            sa.CheckConstraint(
                "(product_id IS NULL) != (variant_id IS NULL)",
                name="ck_product_identifier_exactly_one_owner",
            ),
        )
        op.create_index(
            "ix_product_identifier_product_id", "product_identifier", ["product_id"]
        )
        op.create_index(
            "ix_product_identifier_variant_id", "product_identifier", ["variant_id"]
        )

    # ------------------------------------------------------------------ #
    # category / product_category                                         #
    # ------------------------------------------------------------------ #
    if "category" not in existing_tables:
        op.create_table(
            "category",
            _uuid_pk(),
            sa.Column(
                "parent_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("category.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("code", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=180), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_category_code", "category", ["code"], unique=True)

    if "product_category" not in existing_tables:
        op.create_table(
            "product_category",
            sa.Column(
                "product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "category_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("category.id", ondelete="RESTRICT"),
                primary_key=True,
            ),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # ------------------------------------------------------------------ #
    # tag / product_tag                                                    #
    # ------------------------------------------------------------------ #
    if "tag" not in existing_tables:
        op.create_table(
            "tag",
            _uuid_pk(),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("label", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
        )
        op.create_index("ix_tag_code", "tag", ["code"], unique=True)

    if "product_tag" not in existing_tables:
        op.create_table(
            "product_tag",
            sa.Column(
                "product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "tag_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tag.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )

    # ------------------------------------------------------------------ #
    # price_list / product_price                                          #
    # ------------------------------------------------------------------ #
    if "price_list" not in existing_tables:
        op.create_table(
            "price_list",
            _uuid_pk(),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column(
                "currency", sa.String(length=3), nullable=False, server_default=sa.text("'EUR'")
            ),
            sa.Column(
                "customer_scope",
                sa.String(length=40),
                nullable=False,
                server_default=sa.text("'retail'"),
            ),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "rules",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
        op.create_index("ix_price_list_code", "price_list", ["code"], unique=True)

    if "product_price" not in existing_tables:
        op.create_table(
            "product_price",
            _uuid_pk(),
            sa.Column(
                "variant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_variant.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "price_list_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("price_list.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("net_amount", sa.Numeric(14, 4), nullable=True),
            sa.Column("gross_amount", sa.Numeric(14, 4), nullable=True),
            sa.Column("tax_rate", sa.Numeric(7, 4), nullable=True),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source", sa.String(length=40), nullable=True),
            *_timestamps(),
        )
        op.create_index(
            "ix_product_price_variant_list_valid_from",
            "product_price",
            ["variant_id", "price_list_id", "valid_from"],
        )

    # ------------------------------------------------------------------ #
    # product_asset                                                        #
    # ------------------------------------------------------------------ #
    if "product_asset" not in existing_tables:
        op.create_table(
            "product_asset",
            _uuid_pk(),
            sa.Column(
                "product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "variant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_variant.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("storage_kind", sa.String(length=20), nullable=False),
            sa.Column("uri", sa.Text(), nullable=False),
            sa.Column("original_filename", sa.Text(), nullable=True),
            sa.Column("mime_type", sa.String(length=160), nullable=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
            sa.Column("source_channel", sa.String(length=20), nullable=True),
            sa.Column("source_external_id", sa.String(length=200), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column(
                "public_share_allowed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "health_status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'unknown'"),
            ),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            *_timestamps(),
        )
        op.create_index(
            "ix_product_asset_product_role_sort",
            "product_asset",
            ["product_id", "role", "sort_order"],
        )
        op.create_index("ix_product_asset_variant_id", "product_asset", ["variant_id"])
        op.create_index("ix_product_asset_health_status", "product_asset", ["health_status"])

    # ------------------------------------------------------------------ #
    # print_rule                                                           #
    # ------------------------------------------------------------------ #
    if "print_rule" not in existing_tables:
        op.create_table(
            "print_rule",
            _uuid_pk(),
            sa.Column(
                "variant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_variant.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("min_stock_target", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("reprint_batch_qty", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("print_profile_id", sa.String(length=120), nullable=True),
            sa.Column(
                "print_plan",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "primary_print_asset_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_asset.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_print_rule_variant_id", "print_rule", ["variant_id"], unique=True)

    # ------------------------------------------------------------------ #
    # product_edition                                                      #
    # ------------------------------------------------------------------ #
    if "product_edition" not in existing_tables:
        op.create_table(
            "product_edition",
            _uuid_pk(),
            sa.Column(
                "product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("label", sa.String(length=120), nullable=False),
            sa.Column("edition_number", sa.Integer(), nullable=True),
            sa.Column(
                "status", sa.String(length=40), nullable=False, server_default=sa.text("'draft'")
            ),
            sa.Column("published_at", sa.Date(), nullable=True),
            sa.Column(
                "print_asset_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_asset.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            *_timestamps(),
        )
        op.create_index("ix_product_edition_product_id", "product_edition", ["product_id"])

    # ------------------------------------------------------------------ #
    # product_improvement                                                  #
    # ------------------------------------------------------------------ #
    if "product_improvement" not in existing_tables:
        op.create_table(
            "product_improvement",
            _uuid_pk(),
            sa.Column(
                "product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "variant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_variant.id", ondelete="RESTRICT"),
                nullable=True,
            ),
            sa.Column("title", sa.String(length=300), nullable=True),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column(
                "source",
                sa.String(length=60),
                nullable=False,
                server_default=sa.text("'internal'"),
            ),
            sa.Column("source_reference", sa.Text(), nullable=True),
            sa.Column(
                "severity",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'minor'"),
            ),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default=sa.text("'open'")
            ),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "resolved_in_edition_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_edition.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_product_improvement_product_status",
            "product_improvement",
            ["product_id", "status"],
        )
        op.create_index(
            "ix_product_improvement_severity_status",
            "product_improvement",
            ["severity", "status"],
        )

    # ------------------------------------------------------------------ #
    # channel_mapping                                                      #
    # ------------------------------------------------------------------ #
    if "channel_mapping" not in existing_tables:
        op.create_table(
            "channel_mapping",
            _uuid_pk(),
            sa.Column("channel", sa.String(length=20), nullable=False),
            sa.Column("entity_type", sa.String(length=40), nullable=False),
            sa.Column("internal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("external_id", sa.String(length=240), nullable=False),
            sa.Column("external_parent_id", sa.String(length=240), nullable=True),
            sa.Column("external_revision", sa.String(length=240), nullable=True),
            sa.Column(
                "sync_status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'never'"),
            ),
            sa.Column("last_pulled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_external_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_payload_hash", sa.String(length=64), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint(
                "channel", "entity_type", "external_id", name="uq_channel_mapping_external"
            ),
            sa.UniqueConstraint(
                "channel",
                "entity_type",
                "internal_entity_id",
                name="uq_channel_mapping_internal",
            ),
        )
        op.create_index(
            "ix_channel_mapping_internal_entity_id", "channel_mapping", ["internal_entity_id"]
        )

    # ------------------------------------------------------------------ #
    # channel_category_mapping                                             #
    # ------------------------------------------------------------------ #
    if "channel_category_mapping" not in existing_tables:
        op.create_table(
            "channel_category_mapping",
            _uuid_pk(),
            sa.Column(
                "category_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("category.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("channel", sa.String(length=20), nullable=False),
            sa.Column("external_category_id", sa.String(length=240), nullable=False),
            sa.Column("external_category_name", sa.String(length=240), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.UniqueConstraint(
                "category_id",
                "channel",
                "external_category_id",
                name="uq_channel_category_mapping",
            ),
        )

    # ------------------------------------------------------------------ #
    # audit_log                                                            #
    # ------------------------------------------------------------------ #
    if "audit_log" not in existing_tables:
        op.create_table(
            "audit_log",
            _uuid_pk(),
            sa.Column("actor_type", sa.String(length=40), nullable=False),
            sa.Column("actor_id", sa.String(length=160), nullable=True),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("entity_type", sa.String(length=80), nullable=False),
            sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("action", sa.String(length=40), nullable=False),
            sa.Column(
                "changed_fields",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_audit_log_entity_created",
            "audit_log",
            ["entity_type", "entity_id", "created_at"],
        )

    # ------------------------------------------------------------------ #
    # Seed price lists                                                     #
    # ------------------------------------------------------------------ #
    price_list_t = sa.table(
        "price_list",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("currency", sa.String),
        sa.column("customer_scope", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("rules", postgresql.JSONB),
    )
    existing_price_list_codes = {
        row[0] for row in bind.execute(sa.select(price_list_t.c.code))
    }
    for code, name, scope in (
        ("RETAIL_EUR", "Retail EUR", "retail"),
        ("B2B_EUR", "Händler/B2B EUR", "dealer"),
    ):
        if code not in existing_price_list_codes:
            bind.execute(
                price_list_t.insert().values(
                    id=uuid.uuid4(),
                    code=code,
                    name=name,
                    currency="EUR",
                    customer_scope=scope,
                    active=True,
                    rules={},
                )
            )

    # ------------------------------------------------------------------ #
    # Backfill: one default variant per existing product row               #
    # ------------------------------------------------------------------ #
    if is_fresh_product_hub:
        product_t = sa.table(
            "product",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("sku", sa.String),
            sa.column("name", sa.String),
            sa.column("slug", sa.String),
            sa.column("is_digital", sa.Boolean),
            sa.column("sevdesk_part_id", sa.String),
            sa.column("wix_product_id", sa.String),
            sa.column("print_file_path", sa.Text),
            sa.column("min_stock_target", sa.Integer),
            sa.column("reprint_batch_qty", sa.Integer),
        )
        variant_t = sa.table(
            "product_variant",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("product_id", postgresql.UUID(as_uuid=True)),
            sa.column("sku", sa.String),
            sa.column("name", sa.String),
            sa.column("is_default", sa.Boolean),
            sa.column("active", sa.Boolean),
            sa.column("stock_enabled", sa.Boolean),
            sa.column("option_values", postgresql.JSONB),
            sa.column("attributes", postgresql.JSONB),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        channel_mapping_t = sa.table(
            "channel_mapping",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("channel", sa.String),
            sa.column("entity_type", sa.String),
            sa.column("internal_entity_id", postgresql.UUID(as_uuid=True)),
            sa.column("external_id", sa.String),
            sa.column("sync_status", sa.String),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        asset_t = sa.table(
            "product_asset",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("product_id", postgresql.UUID(as_uuid=True)),
            sa.column("variant_id", postgresql.UUID(as_uuid=True)),
            sa.column("role", sa.String),
            sa.column("sort_order", sa.Integer),
            sa.column("storage_kind", sa.String),
            sa.column("uri", sa.Text),
            sa.column("public_share_allowed", sa.Boolean),
            sa.column("health_status", sa.String),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        print_rule_t = sa.table(
            "print_rule",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("variant_id", postgresql.UUID(as_uuid=True)),
            sa.column("min_stock_target", sa.Integer),
            sa.column("reprint_batch_qty", sa.Integer),
            sa.column("print_plan", postgresql.JSONB),
            sa.column("primary_print_asset_id", postgresql.UUID(as_uuid=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )

        now = datetime.datetime.now(datetime.timezone.utc)
        used_slugs: set[str] = set()
        rows = bind.execute(
            sa.select(
                product_t.c.id,
                product_t.c.sku,
                product_t.c.name,
                product_t.c.is_digital,
                product_t.c.sevdesk_part_id,
                product_t.c.wix_product_id,
                product_t.c.print_file_path,
                product_t.c.min_stock_target,
                product_t.c.reprint_batch_qty,
            )
        ).fetchall()

        for row in rows:
            base_slug = _slugify(row.sku or row.name or str(row.id))
            slug = base_slug
            suffix = 2
            while slug in used_slugs:
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            used_slugs.add(slug)
            bind.execute(
                product_t.update().where(product_t.c.id == row.id).values(slug=slug)
            )

            variant_id = uuid.uuid4()
            normalized_sku = str(row.sku or "").strip().upper()
            bind.execute(
                variant_t.insert().values(
                    id=variant_id,
                    product_id=row.id,
                    sku=normalized_sku,
                    name=row.name,
                    is_default=True,
                    active=True,
                    stock_enabled=not bool(row.is_digital),
                    option_values={},
                    attributes={},
                    created_at=now,
                    updated_at=now,
                )
            )

            if row.wix_product_id:
                bind.execute(
                    channel_mapping_t.insert().values(
                        id=uuid.uuid4(),
                        channel="wix",
                        entity_type="product",
                        internal_entity_id=row.id,
                        external_id=row.wix_product_id,
                        sync_status="never",
                        created_at=now,
                        updated_at=now,
                    )
                )
            if row.sevdesk_part_id:
                bind.execute(
                    channel_mapping_t.insert().values(
                        id=uuid.uuid4(),
                        channel="sevdesk",
                        entity_type="product",
                        internal_entity_id=row.id,
                        external_id=row.sevdesk_part_id,
                        sync_status="never",
                        created_at=now,
                        updated_at=now,
                    )
                )

            primary_asset_id = None
            if row.print_file_path:
                primary_asset_id = uuid.uuid4()
                bind.execute(
                    asset_t.insert().values(
                        id=primary_asset_id,
                        product_id=row.id,
                        variant_id=variant_id,
                        role="PRINT_PDF",
                        sort_order=0,
                        storage_kind="NETWORK_PATH",
                        uri=row.print_file_path,
                        public_share_allowed=False,
                        health_status="unknown",
                        created_at=now,
                        updated_at=now,
                    )
                )

            bind.execute(
                print_rule_t.insert().values(
                    id=uuid.uuid4(),
                    variant_id=variant_id,
                    min_stock_target=row.min_stock_target,
                    reprint_batch_qty=row.reprint_batch_qty,
                    print_plan=[],
                    primary_print_asset_id=primary_asset_id,
                    updated_at=now,
                )
            )

        op.alter_column("product", "slug", nullable=False)
        op.create_index("ix_product_slug", "product", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_product_slug", table_name="product")
    op.drop_index("ix_audit_log_entity_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("channel_category_mapping")
    op.drop_index("ix_channel_mapping_internal_entity_id", table_name="channel_mapping")
    op.drop_table("channel_mapping")
    op.drop_index("ix_product_improvement_severity_status", table_name="product_improvement")
    op.drop_index("ix_product_improvement_product_status", table_name="product_improvement")
    op.drop_table("product_improvement")
    op.drop_index("ix_product_edition_product_id", table_name="product_edition")
    op.drop_table("product_edition")
    op.drop_index("ix_print_rule_variant_id", table_name="print_rule")
    op.drop_table("print_rule")
    op.drop_index("ix_product_asset_health_status", table_name="product_asset")
    op.drop_index("ix_product_asset_variant_id", table_name="product_asset")
    op.drop_index("ix_product_asset_product_role_sort", table_name="product_asset")
    op.drop_table("product_asset")
    op.drop_index("ix_product_price_variant_list_valid_from", table_name="product_price")
    op.drop_table("product_price")
    op.drop_index("ix_price_list_code", table_name="price_list")
    op.drop_table("price_list")
    op.drop_table("product_tag")
    op.drop_index("ix_tag_code", table_name="tag")
    op.drop_table("tag")
    op.drop_table("product_category")
    op.drop_index("ix_category_code", table_name="category")
    op.drop_table("category")
    op.drop_index("ix_product_identifier_variant_id", table_name="product_identifier")
    op.drop_index("ix_product_identifier_product_id", table_name="product_identifier")
    op.drop_table("product_identifier")

    op.drop_index("ix_product_sku_alias_variant_id", table_name="product_sku_alias")
    op.drop_constraint(
        "fk_product_sku_alias_variant_id", "product_sku_alias", type_="foreignkey"
    )
    op.drop_column("product_sku_alias", "variant_id")

    op.drop_index(
        "ix_product_variant_one_default_per_product", table_name="product_variant"
    )
    op.drop_index("ix_product_variant_active", table_name="product_variant")
    op.drop_index("ix_product_variant_product_id", table_name="product_variant")
    op.drop_index("ix_product_variant_sku", table_name="product_variant")
    op.drop_table("product_variant")

    op.drop_column("product", "archived_at")
    op.drop_column("product", "row_version")
    op.drop_column("product", "attributes")
    op.drop_column("product", "release_date")
    op.drop_index("ix_product_active", table_name="product")
    op.drop_column("product", "active")
    op.drop_column("product", "product_type")
    op.drop_index("ix_product_family_id", table_name="product")
    op.drop_constraint("fk_product_family_id", "product", type_="foreignkey")
    op.drop_column("product", "family_id")
    op.drop_column("product", "description")
    op.drop_column("product", "short_description")
    op.drop_column("product", "slug")

    op.drop_index("ix_product_family_code", table_name="product_family")
    op.drop_table("product_family")
