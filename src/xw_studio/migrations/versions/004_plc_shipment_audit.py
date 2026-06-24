"""Add PLC shipment audit and idempotency table.

Revision ID: 004_plc_shipment_audit
Revises: 003_product_brand_fields
Create Date: 2026-06-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_plc_shipment_audit"
down_revision: Union[str, Sequence[str], None] = "003_product_brand_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plc_shipment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("invoice_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("reference", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("invoice_number", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("mode", sa.String(length=8), nullable=False, server_default="LIVE"),
        sa.Column("transport", sa.String(length=32), nullable=False, server_default="webservice"),
        sa.Column("product_code", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("country_iso2", sa.String(length=2), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="sending"),
        sa.Column("tracking_codes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("label_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("print_job_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("error_code", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_plc_shipment_request_key", "plc_shipment", ["request_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_plc_shipment_request_key", table_name="plc_shipment")
    op.drop_table("plc_shipment")
