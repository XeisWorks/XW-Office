"""XW Product Hub PR02: import staging schema (Wix/sevdesk/Excel).

Additive from head 009_product_hub_core. Adds import_batch, staging_product,
staging_variant, staging_identifier, staging_asset, staging_inventory, staging_category
and import_match_candidate. No canonical table (product, product_variant, ...) is
touched — staging is read-only review data until an explicit commit step (PR06).

This migration does not write to Wix or sevdesk and does not touch
``SettingKV["inventory.products"]`` / ``inventory.stock_levels``.

Revision ID: 010_product_hub_import_staging
Revises: 009_product_hub_core
Create Date: 2026-09-16

"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_product_hub_import_staging"
down_revision: Union[str, Sequence[str], None] = "009_product_hub_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk() -> sa.Column[uuid.UUID]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "import_batch" not in existing_tables:
        op.create_table(
            "import_batch",
            _uuid_pk(),
            sa.Column("source", sa.String(length=20), nullable=False),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")
            ),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "source_metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("error_summary", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_import_batch_source", "import_batch", ["source"])

    if "staging_product" not in existing_tables:
        op.create_table(
            "staging_product",
            _uuid_pk(),
            sa.Column(
                "import_batch_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("import_batch.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(length=20), nullable=False),
            sa.Column("source_key", sa.String(length=240), nullable=False),
            sa.Column("source_external_id", sa.String(length=240), nullable=True),
            sa.Column("sku", sa.String(length=80), nullable=True),
            sa.Column("name", sa.String(length=300), nullable=True),
            sa.Column(
                "raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
            ),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "normalized_fields",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("proposed_product_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("proposed_variant_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("match_method", sa.String(length=24), nullable=True),
            sa.Column("match_score", sa.Numeric(5, 4), nullable=True),
            sa.Column(
                "match_status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'unmatched'"),
            ),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column(
                "imported_at",
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
            sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("committed_product_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.UniqueConstraint(
                "import_batch_id",
                "source",
                "source_key",
                name="uq_staging_product_batch_source_key",
            ),
        )
        op.create_index(
            "ix_staging_product_import_batch_id", "staging_product", ["import_batch_id"]
        )
        op.create_index("ix_staging_product_sku", "staging_product", ["sku"])
        op.create_index(
            "ix_staging_product_match_status", "staging_product", ["match_status"]
        )

    if "staging_variant" not in existing_tables:
        op.create_table(
            "staging_variant",
            _uuid_pk(),
            sa.Column(
                "staging_product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("staging_product.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source_external_id", sa.String(length=240), nullable=True),
            sa.Column("sku", sa.String(length=80), nullable=True),
            sa.Column("name", sa.String(length=300), nullable=True),
            sa.Column(
                "option_values",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "raw_payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("proposed_variant_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "match_status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'unmatched'"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_staging_variant_staging_product_id", "staging_variant", ["staging_product_id"]
        )

    if "staging_identifier" not in existing_tables:
        op.create_table(
            "staging_identifier",
            _uuid_pk(),
            sa.Column(
                "staging_product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("staging_product.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("scheme", sa.String(length=20), nullable=False),
            sa.Column("value", sa.String(length=180), nullable=False),
            sa.Column("normalized_value", sa.String(length=180), nullable=False),
            sa.Column("conflict", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_staging_identifier_staging_product_id",
            "staging_identifier",
            ["staging_product_id"],
        )

    if "staging_asset" not in existing_tables:
        op.create_table(
            "staging_asset",
            _uuid_pk(),
            sa.Column(
                "staging_product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("staging_product.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("source_external_id", sa.String(length=240), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_staging_asset_staging_product_id", "staging_asset", ["staging_product_id"]
        )

    if "staging_inventory" not in existing_tables:
        op.create_table(
            "staging_inventory",
            _uuid_pk(),
            sa.Column(
                "staging_product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("staging_product.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("location_external_id", sa.String(length=240), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "stock_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_staging_inventory_staging_product_id",
            "staging_inventory",
            ["staging_product_id"],
        )

    if "staging_category" not in existing_tables:
        op.create_table(
            "staging_category",
            _uuid_pk(),
            sa.Column(
                "staging_product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("staging_product.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("external_category_id", sa.String(length=240), nullable=True),
            sa.Column("external_category_name", sa.String(length=240), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_staging_category_staging_product_id",
            "staging_category",
            ["staging_product_id"],
        )

    if "import_match_candidate" not in existing_tables:
        op.create_table(
            "import_match_candidate",
            _uuid_pk(),
            sa.Column(
                "staging_product_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("staging_product.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("candidate_product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("candidate_variant_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("match_method", sa.String(length=24), nullable=False),
            sa.Column("match_score", sa.Numeric(5, 4), nullable=True),
            sa.Column("rank", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_import_match_candidate_staging_product_rank",
            "import_match_candidate",
            ["staging_product_id", "rank"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_import_match_candidate_staging_product_rank",
        table_name="import_match_candidate",
    )
    op.drop_table("import_match_candidate")
    op.drop_index("ix_staging_category_staging_product_id", table_name="staging_category")
    op.drop_table("staging_category")
    op.drop_index("ix_staging_inventory_staging_product_id", table_name="staging_inventory")
    op.drop_table("staging_inventory")
    op.drop_index("ix_staging_asset_staging_product_id", table_name="staging_asset")
    op.drop_table("staging_asset")
    op.drop_index(
        "ix_staging_identifier_staging_product_id", table_name="staging_identifier"
    )
    op.drop_table("staging_identifier")
    op.drop_index("ix_staging_variant_staging_product_id", table_name="staging_variant")
    op.drop_table("staging_variant")
    op.drop_index("ix_staging_product_match_status", table_name="staging_product")
    op.drop_index("ix_staging_product_sku", table_name="staging_product")
    op.drop_index("ix_staging_product_import_batch_id", table_name="staging_product")
    op.drop_table("staging_product")
    op.drop_index("ix_import_batch_source", table_name="import_batch")
    op.drop_table("import_batch")
