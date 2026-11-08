"""Persist deduplicated inventory alert task mail attempts."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "033_inventory_alert_task"
down_revision = "032_inventory_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "inventory_alert_task" in set(inspector.get_table_names()):
        return
    op.create_table(
        "inventory_alert_task",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("alert_id", sa.Uuid(), sa.ForeignKey("inventory_alert.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(320), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("alert_id", name="uq_inventory_alert_task_alert"),
    )
    op.create_index("ix_inventory_alert_task_alert_id", "inventory_alert_task", ["alert_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "inventory_alert_task" in set(inspector.get_table_names()):
        op.drop_table("inventory_alert_task")
