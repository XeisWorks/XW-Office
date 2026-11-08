"""Persist forecast provenance for alert and task presentation."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "035_inventory_forecast_metadata"
down_revision = "034_inventory_forecast_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("inventory_stock")}
    additions = (
        ("forecast_net_sold_units", sa.Integer(), "0"),
        ("forecast_full_sellable_months", sa.Integer(), "0"),
        ("forecast_window_start", sa.Date(), None),
        ("forecast_window_end", sa.Date(), None),
        ("forecast_data_quality", sa.String(40), "unknown"),
        ("forecast_refreshed_at", sa.DateTime(timezone=True), None),
    )
    for name, type_, default in additions:
        if name not in columns:
            kwargs = {"nullable": True} if default is None else {"nullable": False, "server_default": default}
            op.add_column("inventory_stock", sa.Column(name, type_, **kwargs))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("inventory_stock")}
    for name in (
        "forecast_refreshed_at",
        "forecast_data_quality",
        "forecast_window_end",
        "forecast_window_start",
        "forecast_full_sellable_months",
        "forecast_net_sold_units",
    ):
        if name in columns:
            op.drop_column("inventory_stock", name)

