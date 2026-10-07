"""Add recipient-scoped bank-purpose display rules.

Revision ID: 024_expense_purpose_rules
Revises: 023_expense_document_scan_cache
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "024_expense_purpose_rules"
down_revision = "023_expense_document_scan_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "expense_purpose_rule" not in existing:
        op.create_table(
            "expense_purpose_rule",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("payee_normalized", sa.String(300), nullable=False),
            sa.Column("remove_text", sa.Text(), nullable=False),
            sa.Column("label", sa.String(200), nullable=False, server_default=""),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("expense_purpose_rule")}
    if "ix_expense_purpose_rule_enabled" not in indexes:
        op.create_index(
            "ix_expense_purpose_rule_enabled",
            "expense_purpose_rule",
            ["enabled", "payee_normalized"],
        )


def downgrade() -> None:
    op.drop_index("ix_expense_purpose_rule_enabled", table_name="expense_purpose_rule")
    op.drop_table("expense_purpose_rule")
