"""XW Product Hub PR12: dealer sharing (shared_catalog_view + export_log).

Additive from head 012_product_hub_sync_outbox. Schema per
docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml: ``shared_catalog_view`` (a revocable,
field-whitelisted, token-hashed dealer/public catalog view) and ``export_log`` (one
row per CSV/XLSX export served through a share).

Per the data model's own rules: only ``token_hash`` (SHA-256 hex, 64 chars) is ever
stored — the plaintext token is generated and returned once at creation and never
persisted anywhere, including this table.

This migration does not write to Wix or sevdesk and does not touch
``SettingKV["inventory.products"]`` / ``inventory.stock_levels``.

Revision ID: 013_product_hub_sharing
Revises: 012_product_hub_sync_outbox
Create Date: 2026-09-16

"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013_product_hub_sharing"
down_revision: Union[str, Sequence[str], None] = "012_product_hub_sync_outbox"
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

    if "shared_catalog_view" not in existing_tables:
        op.create_table(
            "shared_catalog_view",
            _uuid_pk(),
            sa.Column("title", sa.String(220), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("password_hash", sa.Text(), nullable=True),
            sa.Column(
                "filter_definition",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "field_whitelist",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "sort_definition",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "price_list_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("price_list.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("allow_csv", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("allow_xlsx", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("allow_images", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_shared_catalog_view_token_hash", "shared_catalog_view", ["token_hash"], unique=True
        )

    if "export_log" not in existing_tables:
        op.create_table(
            "export_log",
            _uuid_pk(),
            sa.Column(
                "shared_view_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("shared_catalog_view.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("format", sa.String(20), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("query_hash", sa.String(64), nullable=False),
            sa.Column(
                "generated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("requested_by", sa.String(160), nullable=True),
        )
        op.create_index("ix_export_log_shared_view_id", "export_log", ["shared_view_id"])


def downgrade() -> None:
    op.drop_index("ix_export_log_shared_view_id", table_name="export_log")
    op.drop_table("export_log")
    op.drop_index("ix_shared_catalog_view_token_hash", table_name="shared_catalog_view")
    op.drop_table("shared_catalog_view")
