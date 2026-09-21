"""Durable dispositions for Wix-only reconciliation items.

Revision ID: 017_wix_reconciliation_disposition
Revises: 016_conflict_wizard
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "017_wix_reconciliation_disposition"
down_revision = "016_conflict_wizard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "wix_reconciliation_disposition" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "wix_reconciliation_disposition",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("external_id", sa.String(240), nullable=False),
        sa.Column("variant_external_id", sa.String(240), nullable=False, server_default=sa.text("''")),
        sa.Column("disposition", sa.String(20), nullable=False),
        sa.Column("deferred_until", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("external_id", "variant_external_id", name="uq_wix_reconciliation_item"),
    )
    op.create_index(
        "ix_wix_reconciliation_disposition_due", "wix_reconciliation_disposition",
        ["disposition", "deferred_until"],
    )


def downgrade() -> None:
    op.drop_table("wix_reconciliation_disposition")
