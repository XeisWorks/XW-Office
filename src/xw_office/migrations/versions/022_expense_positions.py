"""Add configurable expense positions and composite assignment rules.

Revision ID: 022_expense_positions
Revises: 021_expense_pipeline
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "022_expense_positions"
down_revision = "021_expense_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    position_created = "expense_position" not in existing
    if position_created:
        op.create_table(
            "expense_position",
            sa.Column("key", sa.String(32), primary_key=True, nullable=False),
            sa.Column("label", sa.String(100), nullable=False),
            sa.Column("initials", sa.String(8), nullable=False),
            sa.Column("color", sa.String(16), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    if "expense_position_rule" not in existing:
        op.create_table(
            "expense_position_rule",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("position_key", sa.String(32), nullable=False),
            sa.Column("label", sa.String(200), nullable=False, server_default=""),
            sa.Column("payee_normalized", sa.String(300), nullable=False, server_default=""),
            sa.Column("counterparty_iban", sa.String(64), nullable=False, server_default=""),
            sa.Column("purpose_contains", sa.Text(), nullable=False, server_default=""),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    if "expense_position_assignment" not in existing:
        op.create_table(
            "expense_position_assignment",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
            sa.Column("position_key", sa.String(32), nullable=False),
            sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("matched_rule_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    rule_indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("expense_position_rule")
    }
    if "ix_expense_position_rule_enabled" not in rule_indexes:
        op.create_index(
            "ix_expense_position_rule_enabled",
            "expense_position_rule",
            ["enabled", "priority"],
        )
    if position_created:
        op.bulk_insert(
            sa.table(
                "expense_position",
                sa.column("key", sa.String), sa.column("label", sa.String),
                sa.column("initials", sa.String), sa.column("color", sa.String),
                sa.column("sort_order", sa.Integer), sa.column("enabled", sa.Boolean),
            ),
            [
                {"key": "xw", "label": "XeisWorks", "initials": "XW", "color": "#c6922d", "sort_order": 10, "enabled": True},
                {"key": "mh", "label": "MusikHeroes", "initials": "MH", "color": "#c0392b", "sort_order": 20, "enabled": True},
                {"key": "wm", "label": "WüdaraMusi", "initials": "WM", "color": "#2e8b57", "sort_order": 30, "enabled": True},
                {"key": "bh", "label": "Blechhaufn", "initials": "BH", "color": "#2878b5", "sort_order": 40, "enabled": True},
                {"key": "priv", "label": "Privat", "initials": "PRIV", "color": "#777777", "sort_order": 50, "enabled": True},
            ],
        )


def downgrade() -> None:
    op.drop_index("ix_expense_position_rule_enabled", table_name="expense_position_rule")
    op.drop_table("expense_position_assignment")
    op.drop_table("expense_position_rule")
    op.drop_table("expense_position")
