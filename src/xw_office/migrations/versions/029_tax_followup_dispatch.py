"""Persist idempotent tax follow-up mail attempts."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "029_tax_followup_dispatch"
down_revision = "028_invoice_search_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tax_followup_dispatches" in set(inspector.get_table_names()):
        return
    op.create_table(
        "tax_followup_dispatches",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("dispatch_key", sa.String(220), nullable=False),
        sa.Column("filing_kind", sa.String(20), nullable=False),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("calculation_hash", sa.String(64), nullable=False),
        sa.Column("recipient_kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_correlation_id", sa.String(64), nullable=False),
        sa.Column("attachment_sha256", sa.String(64), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
        sa.UniqueConstraint("dispatch_key", name="uq_tax_followup_dispatch_key"),
        sa.UniqueConstraint(
            "filing_kind", "period", "calculation_hash", "recipient_kind",
            name="uq_tax_followup_dispatch_identity",
        ),
    )
    op.create_index("ix_tax_followup_dispatches_dispatch_key", "tax_followup_dispatches", ["dispatch_key"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tax_followup_dispatches" in set(inspector.get_table_names()):
        op.drop_table("tax_followup_dispatches")
