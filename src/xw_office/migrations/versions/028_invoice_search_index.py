"""Add the shared sevDesk invoice search index.

Revision ID: 028_invoice_search_index
Revises: 027_customer_aftercare_snooze_context
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "028_invoice_search_index"
down_revision = "027_customer_aftercare_snooze_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "invoice_search_index" in set(inspector.get_table_names()):
        return
    op.create_table(
        "invoice_search_index",
        sa.Column("invoice_id", sa.String(32), primary_key=True),
        sa.Column("invoice_number", sa.String(100), nullable=False, server_default=""),
        sa.Column("invoice_date", sa.String(40), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_invoice_search_index_invoice_number", "invoice_search_index", ["invoice_number"]
    )
    op.create_index("ix_invoice_search_index_synced_at", "invoice_search_index", ["synced_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "invoice_search_index" in set(inspector.get_table_names()):
        op.drop_table("invoice_search_index")
