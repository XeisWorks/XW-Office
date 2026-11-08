"""Add guided inventory count sessions and lines."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "032_inventory_count"
down_revision = "031_credit_note_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "inventory_count_session" not in tables:
        op.create_table(
            "inventory_count_session",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
            sa.Column("location_code", sa.String(32), nullable=False, server_default="MAIN"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_by", sa.String(128), nullable=False, server_default=""),
            sa.Column("baseline_source_hash", sa.String(128), nullable=False, server_default=""),
            sa.Column("counted_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "inventory_count_line" not in tables:
        op.create_table(
            "inventory_count_line",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("session_id", sa.Uuid(), sa.ForeignKey("inventory_count_session.id", ondelete="CASCADE"), nullable=False),
            sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("product_variant.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("location_code", sa.String(32), nullable=False),
            sa.Column("sku", sa.String(80), nullable=False),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("system_quantity", sa.Integer(), nullable=False),
            sa.Column("counted_quantity", sa.Integer(), nullable=True),
            sa.Column("difference", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(24), nullable=False, server_default="open"),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("movement_id", sa.Uuid(), nullable=True),
            sa.Column("idempotency_key", sa.String(240), nullable=False, server_default=""),
            sa.Column("counted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("session_id", "variant_id", "location_code", name="uq_inventory_count_line_variant"),
        )
        op.create_index("ix_inventory_count_line_session_id", "inventory_count_line", ["session_id"])
        op.create_index("ix_inventory_count_line_variant_id", "inventory_count_line", ["variant_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "inventory_count_line" in tables:
        op.drop_table("inventory_count_line")
    if "inventory_count_session" in tables:
        op.drop_table("inventory_count_session")
