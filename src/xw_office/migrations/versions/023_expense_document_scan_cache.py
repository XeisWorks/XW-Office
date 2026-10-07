"""Cache completed sevDesk expense-document scans.

Revision ID: 023_expense_document_scan_cache
Revises: 022_expense_positions
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "023_expense_document_scan_cache"
down_revision = "022_expense_positions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "expense_document_scan" not in existing:
        op.create_table(
            "expense_document_scan",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("resource_type", sa.String(32), nullable=False),
            sa.Column("external_id", sa.String(200), nullable=False),
            sa.Column("fingerprint", sa.String(128), nullable=False),
            sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("resource_type", "external_id", name="uq_expense_document_scan"),
        )
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("expense_document_scan")}
    if "ix_expense_document_scan_fingerprint" not in indexes:
        op.create_index(
            "ix_expense_document_scan_fingerprint",
            "expense_document_scan",
            ["resource_type", "fingerprint"],
        )


def downgrade() -> None:
    op.drop_index("ix_expense_document_scan_fingerprint", table_name="expense_document_scan")
    op.drop_table("expense_document_scan")
