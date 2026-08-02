"""Add Ausgaben-Check ignore rules and period shift entries.

Revision ID: 006_expense_check
Revises: 005_plc_print_statistics
Create Date: 2026-07-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_expense_check"
down_revision: Union[str, Sequence[str], None] = "005_plc_print_statistics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "expense_ignore_rule" not in existing_tables:
        op.create_table(
            "expense_ignore_rule",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("mandant", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("pattern_original", sa.Text(), nullable=False, server_default=""),
            sa.Column("pattern_normalized", sa.Text(), nullable=False),
            sa.Column("scope", sa.String(length=16), nullable=False, server_default="forever"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_expense_ignore_rule_mandant", "expense_ignore_rule", ["mandant"], unique=False
        )

    if "expense_shift_entry" not in existing_tables:
        op.create_table(
            "expense_shift_entry",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("mandant", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("transaction_ref", sa.String(length=200), nullable=False),
            sa.Column("source_period", sa.String(length=7), nullable=False),
            sa.Column("target_period", sa.String(length=7), nullable=False),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_expense_shift_entry_transaction_ref",
            "expense_shift_entry",
            ["transaction_ref"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_expense_shift_entry_transaction_ref", table_name="expense_shift_entry")
    op.drop_table("expense_shift_entry")
    op.drop_index("ix_expense_ignore_rule_mandant", table_name="expense_ignore_rule")
    op.drop_table("expense_ignore_rule")
