"""Durable Product Hub asset-render jobs and immutable source versions.

Revision ID: 019_product_asset_jobs
Revises: 018_product_wizard_drafts
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "019_product_asset_jobs"
down_revision = "018_product_wizard_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    product_asset_columns = {column["name"] for column in inspector.get_columns("product_asset")}
    if "source_version" not in product_asset_columns:
        op.add_column("product_asset", sa.Column("source_version", sa.String(300), nullable=True))
    if "product_asset_job" not in tables:
        json = postgresql.JSONB(astext_type=sa.Text()) if bind.dialect.name == "postgresql" else sa.JSON()
        uuid = postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.Uuid()
        op.create_table(
            "product_asset_job",
            sa.Column("id", uuid, primary_key=True),
            sa.Column("product_id", uuid, sa.ForeignKey("product.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_asset_id", uuid, sa.ForeignKey("product_asset.id", ondelete="CASCADE"), nullable=False),
            sa.Column("variant_id", uuid, sa.ForeignKey("product_variant.id", ondelete="SET NULL")),
            sa.Column("job_key", sa.String(64), nullable=False),
            sa.Column("recipe", json, nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("output_manifest", json, nullable=False, server_default=sa.text("'[]'::jsonb") if bind.dialect.name == "postgresql" else sa.text("'[]'")),
            sa.Column("last_error", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("job_key", name="uq_product_asset_job_key"),
        )
        op.create_index("ix_product_asset_job_product_status", "product_asset_job", ["product_id", "status"])


def downgrade() -> None:
    op.drop_table("product_asset_job")
    op.drop_column("product_asset", "source_version")
