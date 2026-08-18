"""Add Lieferkorrekturen (customer aftercare) case and item tables.

Revision ID: 007_customer_aftercare
Revises: 006_expense_check
Create Date: 2026-08-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007_customer_aftercare"
down_revision: Union[str, Sequence[str], None] = "006_expense_check"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "customer_aftercare_case" not in existing_tables:
        op.create_table(
            "customer_aftercare_case",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("case_type", sa.String(length=40), nullable=False, server_default=""),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default="PENDING_REVIEW"
            ),
            sa.Column("source_message_id", sa.String(length=255), nullable=False),
            sa.Column("source_thread_id", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("source_subject", sa.Text(), nullable=False, server_default=""),
            sa.Column("ai_suggested_type", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("ai_confidence", sa.Numeric(4, 3), nullable=True),
            sa.Column("ai_payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("classification_confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("customer_type", sa.String(length=10), nullable=False, server_default=""),
            sa.Column("wix_contact_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("customer_email", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("customer_name", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("source_wix_order_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column(
                "source_wix_order_number", sa.String(length=64), nullable=False, server_default=""
            ),
            sa.Column("source_order_created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("courtesy", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("wait_for_next_order", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("trigger_reason", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("trigger_wix_order_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column(
                "trigger_wix_order_number", sa.String(length=64), nullable=False, server_default=""
            ),
            sa.Column("invoice_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("invoice_status", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("sevdesk_invoice_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column(
                "sevdesk_invoice_number", sa.String(length=64), nullable=False, server_default=""
            ),
            sa.Column("invoice_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_customer_aftercare_case_source_message_id",
            "customer_aftercare_case",
            ["source_message_id"],
            unique=True,
        )
        op.create_index(
            "ix_customer_aftercare_case_status", "customer_aftercare_case", ["status"], unique=False
        )
        op.create_index(
            "ix_customer_aftercare_case_due_at", "customer_aftercare_case", ["due_at"], unique=False
        )

    if "customer_aftercare_item" not in existing_tables:
        op.create_table(
            "customer_aftercare_item",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "case_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("customer_aftercare_case.id"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("sku", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("sevdesk_part_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("source_unit_price", sa.Numeric(10, 2), nullable=True),
            sa.Column("source_tax_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("source_discount_percent", sa.Numeric(5, 2), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_customer_aftercare_item_case_id", "customer_aftercare_item", ["case_id"], unique=False
        )


def downgrade() -> None:
    op.drop_index("ix_customer_aftercare_item_case_id", table_name="customer_aftercare_item")
    op.drop_table("customer_aftercare_item")
    op.drop_index("ix_customer_aftercare_case_due_at", table_name="customer_aftercare_case")
    op.drop_index("ix_customer_aftercare_case_status", table_name="customer_aftercare_case")
    op.drop_index(
        "ix_customer_aftercare_case_source_message_id", table_name="customer_aftercare_case"
    )
    op.drop_table("customer_aftercare_case")
