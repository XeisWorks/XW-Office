"""Persist automatic reorder proposal and active threshold mode."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "034_inventory_forecast_fields"
down_revision = "033_inventory_alert_task"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("inventory_stock")}
    if "automatic_reorder_point" not in columns:
        op.add_column("inventory_stock", sa.Column("automatic_reorder_point", sa.Integer(), nullable=False, server_default="0"))
    if "reorder_mode" not in columns:
        op.add_column("inventory_stock", sa.Column("reorder_mode", sa.String(12), nullable=False, server_default="auto"))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("inventory_stock")}
    if "reorder_mode" in columns:
        op.drop_column("inventory_stock", "reorder_mode")
    if "automatic_reorder_point" in columns:
        op.drop_column("inventory_stock", "automatic_reorder_point")
