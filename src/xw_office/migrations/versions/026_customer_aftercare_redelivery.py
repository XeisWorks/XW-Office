"""Extend customer aftercare for invoice-created redelivery dispatches.

Revision ID: 026_customer_aftercare_redelivery
Revises: 025_expense_pipeline_tenant_purpose_rules
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "026_customer_aftercare_redelivery"
down_revision = "025_expense_pipeline_tenant_purpose_rules"
branch_labels = None
depends_on = None


_CASE_COLUMNS = {
    "sevdesk_contact_id": sa.Column("sevdesk_contact_id", sa.String(64), nullable=False, server_default=""),
    "source_invoice_id": sa.Column("source_invoice_id", sa.String(64), nullable=False, server_default=""),
    "source_invoice_number": sa.Column("source_invoice_number", sa.String(64), nullable=False, server_default=""),
    "address_lines_json": sa.Column("address_lines_json", sa.Text(), nullable=False, server_default="[]"),
    "address_source": sa.Column("address_source", sa.String(32), nullable=False, server_default=""),
    "shipping_mode": sa.Column("shipping_mode", sa.String(32), nullable=False, server_default="WAIT_NEXT_ORDER_OR_DEADLINE"),
    "trigger_invoice_id": sa.Column("trigger_invoice_id", sa.String(64), nullable=False, server_default=""),
    "trigger_invoice_number": sa.Column("trigger_invoice_number", sa.String(64), nullable=False, server_default=""),
    "dispatch_id": sa.Column("dispatch_id", sa.String(64), nullable=False, server_default=""),
    "dispatch_status": sa.Column("dispatch_status", sa.String(32), nullable=False, server_default=""),
    "delivery_note_path": sa.Column("delivery_note_path", sa.Text(), nullable=False, server_default=""),
    "delivery_note_printed_at": sa.Column("delivery_note_printed_at", sa.DateTime(timezone=True), nullable=True),
}

_ITEM_COLUMNS = {
    "source_kind": sa.Column("source_kind", sa.String(32), nullable=False, server_default=""),
    "source_item_id": sa.Column("source_item_id", sa.String(128), nullable=False, server_default=""),
    "parent_sku": sa.Column("parent_sku", sa.String(64), nullable=False, server_default=""),
    "component_id": sa.Column("component_id", sa.String(128), nullable=False, server_default=""),
    "origin_invoice_number": sa.Column("origin_invoice_number", sa.String(64), nullable=False, server_default=""),
    "origin_order_number": sa.Column("origin_order_number", sa.String(64), nullable=False, server_default=""),
    "note": sa.Column("note", sa.Text(), nullable=False, server_default=""),
}


def _add_missing_columns(table: str, columns: dict[str, sa.Column]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {item["name"] for item in inspector.get_columns(table)}
    for name, column in columns.items():
        if name not in existing:
            op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "customer_aftercare_case" in tables:
        _add_missing_columns("customer_aftercare_case", _CASE_COLUMNS)
        # PostgreSQL accepts this widening operation; SQLite test databases
        # already tolerate the existing String length declaration.
        if bind.dialect.name == "postgresql":
            op.alter_column("customer_aftercare_case", "status", type_=sa.String(32))
    if "customer_aftercare_item" in tables:
        _add_missing_columns("customer_aftercare_item", _ITEM_COLUMNS)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    case_columns = {item["name"] for item in inspector.get_columns("customer_aftercare_case")}
    item_columns = {item["name"] for item in inspector.get_columns("customer_aftercare_item")}
    for name in reversed(tuple(_ITEM_COLUMNS)):
        if name in item_columns:
            op.drop_column("customer_aftercare_item", name)
    for name in reversed(tuple(_CASE_COLUMNS)):
        if name in case_columns:
            op.drop_column("customer_aftercare_case", name)
