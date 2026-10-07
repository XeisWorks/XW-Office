"""Scope expense-purpose cleanup rules to a sevDesk tenant.

Revision ID: 025_expense_pipeline_tenant_purpose_rules
Revises: 024_expense_purpose_rules
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "025_expense_pipeline_tenant_purpose_rules"
down_revision = "024_expense_purpose_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("expense_purpose_rule")}
    if "tenant_key" not in columns:
        op.add_column(
            "expense_purpose_rule",
            sa.Column("tenant_key", sa.String(32), nullable=False, server_default="xw"),
        )
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("expense_purpose_rule")}
    if "ix_expense_purpose_rule_tenant" not in indexes:
        op.create_index("ix_expense_purpose_rule_tenant", "expense_purpose_rule", ["tenant_key"])


def downgrade() -> None:
    op.drop_index("ix_expense_purpose_rule_tenant", table_name="expense_purpose_rule")
    op.drop_column("expense_purpose_rule", "tenant_key")
