"""Add snooze state and immutable source context to customer aftercare.

Revision ID: 027_customer_aftercare_snooze_context
Revises: 026_customer_aftercare_redelivery
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "027_customer_aftercare_snooze_context"
down_revision = "026_customer_aftercare_redelivery"
branch_labels = None
depends_on = None


_COLUMNS = {
    "source_invoice_date": sa.Column(
        "source_invoice_date", sa.String(32), nullable=False, server_default=""
    ),
    "source_mail_sender": sa.Column(
        "source_mail_sender", sa.String(255), nullable=False, server_default=""
    ),
    "source_mail_body": sa.Column("source_mail_body", sa.Text(), nullable=False, server_default=""),
    "snooze_mode": sa.Column("snooze_mode", sa.String(32), nullable=False, server_default=""),
    "snoozed_until": sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
    "snooze_reason": sa.Column("snooze_reason", sa.Text(), nullable=False, server_default=""),
    "snoozed_at": sa.Column("snoozed_at", sa.DateTime(timezone=True), nullable=True),
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_aftercare_case" not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_columns("customer_aftercare_case")}
    for name, column in _COLUMNS.items():
        if name not in existing:
            op.add_column("customer_aftercare_case", column)
    indexes = {item["name"] for item in inspector.get_indexes("customer_aftercare_case")}
    if "ix_customer_aftercare_case_snoozed_until" not in indexes:
        op.create_index(
            "ix_customer_aftercare_case_snoozed_until",
            "customer_aftercare_case",
            ["snoozed_until"],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes("customer_aftercare_case")}
    if "ix_customer_aftercare_case_snoozed_until" in indexes:
        op.drop_index(
            "ix_customer_aftercare_case_snoozed_until", table_name="customer_aftercare_case"
        )
    existing = {item["name"] for item in inspector.get_columns("customer_aftercare_case")}
    for name in reversed(tuple(_COLUMNS)):
        if name in existing:
            op.drop_column("customer_aftercare_case", name)
