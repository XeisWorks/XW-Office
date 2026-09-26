"""Durable product-wizard drafts, options and selected combinations.

Revision ID: 018_product_wizard_drafts
Revises: 017_wix_reconciliation_disposition
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "018_product_wizard_drafts"
down_revision = "017_wix_reconciliation_disposition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    json = postgresql.JSONB(astext_type=sa.Text()) if bind.dialect.name == "postgresql" else sa.JSON()
    uuid = postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.Uuid()
    now = sa.func.now()
    if "product_draft" not in tables:
        op.create_table(
            "product_draft",
            sa.Column("id", uuid, primary_key=True),
            sa.Column("source_product_id", uuid, sa.ForeignKey("product.id", ondelete="SET NULL")),
            sa.Column("template_code", sa.String(80)),
            sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("completed_steps", json, nullable=False, server_default=sa.text("'[]'::jsonb") if bind.dialect.name == "postgresql" else sa.text("'[]'")),
            sa.Column("data", json, nullable=False, server_default=sa.text("'{}'::jsonb") if bind.dialect.name == "postgresql" else sa.text("'{}'")),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        )
        op.create_index("ix_product_draft_source_product_id", "product_draft", ["source_product_id"])
    if "product_draft_option" not in tables:
        op.create_table(
            "product_draft_option",
            sa.Column("id", uuid, primary_key=True),
            sa.Column("draft_id", uuid, sa.ForeignKey("product_draft.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("values", json, nullable=False, server_default=sa.text("'[]'::jsonb") if bind.dialect.name == "postgresql" else sa.text("'[]'")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.UniqueConstraint("draft_id", "name", name="uq_product_draft_option_name"),
        )
        op.create_index("ix_product_draft_option_draft_id", "product_draft_option", ["draft_id"])
    if "product_draft_variant" not in tables:
        op.create_table(
            "product_draft_variant",
            sa.Column("id", uuid, primary_key=True),
            sa.Column("draft_id", uuid, sa.ForeignKey("product_draft.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sku", sa.String(80), nullable=False),
            sa.Column("option_values", json, nullable=False, server_default=sa.text("'{}'::jsonb") if bind.dialect.name == "postgresql" else sa.text("'{}'")),
            sa.Column("price_gross", sa.Numeric(14, 4)),
            sa.Column("tax_rate", sa.Numeric(7, 4)),
            sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.UniqueConstraint("draft_id", "sku", name="uq_product_draft_variant_sku"),
        )
        op.create_index("ix_product_draft_variant_draft_id", "product_draft_variant", ["draft_id"])


def downgrade() -> None:
    op.drop_table("product_draft_variant")
    op.drop_table("product_draft_option")
    op.drop_table("product_draft")
