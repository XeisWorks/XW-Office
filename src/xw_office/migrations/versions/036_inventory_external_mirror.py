"""Persist idempotent external sevDesk-to-Legacy stock mirror events."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036_inventory_external_mirror"
down_revision = "035_inventory_forecast_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "inventory_external_mirror" in set(inspector.get_table_names()):
        return
    op.create_table(
        "inventory_external_mirror",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("idempotency_key", sa.String(240), nullable=False),
        sa.Column("sku", sa.String(160), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("previous_stock", sa.Integer(), nullable=False),
        sa.Column("new_stock", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("external_reference", sa.String(240), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_inventory_external_mirror_key"),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "inventory_external_mirror" in set(inspector.get_table_names()):
        op.drop_table("inventory_external_mirror")
