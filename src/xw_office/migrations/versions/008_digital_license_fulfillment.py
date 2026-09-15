"""Add persistent manual digital-license fulfillment state.

Revision ID: 008_digital_license_fulfillment
Revises: 007_customer_aftercare
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_digital_license_fulfillment"
down_revision: Union[str, Sequence[str], None] = "007_customer_aftercare"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "digital_license_fulfillment" in set(inspector.get_table_names()):
        return
    op.create_table(
        "digital_license_fulfillment",
        sa.Column("invoice_id", sa.String(length=128), primary_key=True, nullable=False),
        sa.Column("invoice_number", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("order_reference", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="PENDING_DECISION"),
        sa.Column("licensed_files_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("invoice_attachment_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("outlook_entry_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("outlook_store_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("invoice_finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deferred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draft_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wix_fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_digital_license_fulfillment_order_reference",
        "digital_license_fulfillment",
        ["order_reference"],
    )
    op.create_index(
        "ix_digital_license_fulfillment_state",
        "digital_license_fulfillment",
        ["state"],
    )


def downgrade() -> None:
    op.drop_index("ix_digital_license_fulfillment_state", table_name="digital_license_fulfillment")
    op.drop_index("ix_digital_license_fulfillment_order_reference", table_name="digital_license_fulfillment")
    op.drop_table("digital_license_fulfillment")
