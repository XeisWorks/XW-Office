"""Add successful PLC print statistics fields.

Revision ID: 005_plc_print_statistics
Revises: 004_plc_shipment_audit
Create Date: 2026-07-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_plc_print_statistics"
down_revision: Union[str, Sequence[str], None] = "004_plc_shipment_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {str(column["name"]) for column in inspector.get_columns("plc_shipment")}
    if "weight_kg" not in columns:
        op.add_column("plc_shipment", sa.Column("weight_kg", sa.Numeric(8, 3), nullable=True))
    if "price_eur" not in columns:
        op.add_column("plc_shipment", sa.Column("price_eur", sa.Numeric(10, 2), nullable=True))
    if "printed_at" not in columns:
        op.add_column(
            "plc_shipment",
            sa.Column("printed_at", sa.DateTime(timezone=True), nullable=True),
        )

    inspector = sa.inspect(op.get_bind())
    index_names = {str(index.get("name") or "") for index in inspector.get_indexes("plc_shipment")}
    if "ix_plc_shipment_printed_at" not in index_names:
        op.create_index("ix_plc_shipment_printed_at", "plc_shipment", ["printed_at"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    index_names = {str(index.get("name") or "") for index in inspector.get_indexes("plc_shipment")}
    if "ix_plc_shipment_printed_at" in index_names:
        op.drop_index("ix_plc_shipment_printed_at", table_name="plc_shipment")
    columns = {str(column["name"]) for column in inspector.get_columns("plc_shipment")}
    if "printed_at" in columns:
        op.drop_column("plc_shipment", "printed_at")
    if "price_eur" in columns:
        op.drop_column("plc_shipment", "price_eur")
    if "weight_kg" in columns:
        op.drop_column("plc_shipment", "weight_kg")
