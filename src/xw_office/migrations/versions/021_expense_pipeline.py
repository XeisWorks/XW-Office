"""Add shared bank-expense snapshots, links, flags, and rules.

Revision ID: 021_expense_pipeline
Revises: 020_print_center
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "021_expense_pipeline"
down_revision = "020_print_center"
branch_labels = None
depends_on = None


def _uuid(name: str) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), primary_key=True, nullable=False)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "expense_import_run" not in existing:
        op.create_table(
            "expense_import_run",
            _uuid("id"),
            sa.Column("account_id", sa.String(100), nullable=False),
            sa.Column("account_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("period_start", sa.Date(), nullable=True),
            sa.Column("period_end", sa.Date(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="running"),
            sa.Column("sevdesk_last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("transaction_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("linked_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_text", sa.Text(), nullable=False, server_default=""),
        )
    if "expense_transaction_snapshot" not in existing:
        op.create_table(
            "expense_transaction_snapshot",
            _uuid("id"),
            sa.Column("account_id", sa.String(100), nullable=False),
            sa.Column("external_id", sa.String(200), nullable=False),
            sa.Column("value_date", sa.Date(), nullable=False),
            sa.Column("entry_date", sa.Date(), nullable=True),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("currency", sa.String(8), nullable=False, server_default="EUR"),
            sa.Column("direction", sa.String(16), nullable=False, server_default="outgoing"),
            sa.Column("payee_name", sa.String(300), nullable=False, server_default=""),
            sa.Column("payee_normalized", sa.String(300), nullable=False, server_default=""),
            sa.Column("counterparty_iban", sa.String(64), nullable=False, server_default=""),
            sa.Column("payment_reference", sa.Text(), nullable=False, server_default=""),
            sa.Column("purpose", sa.Text(), nullable=False, server_default=""),
            sa.Column("sevdesk_status", sa.String(32), nullable=False, server_default=""),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("account_id", "external_id", name="uq_expense_tx_account_external"),
        )
    if "expense_document_link" not in existing:
        op.create_table(
            "expense_document_link",
            _uuid("id"),
            sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("resource_type", sa.String(32), nullable=False),
            sa.Column("external_id", sa.String(200), nullable=False),
            sa.Column("document_number", sa.String(200), nullable=False, server_default=""),
            sa.Column("source", sa.String(32), nullable=False, server_default="sevdesk"),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("transaction_id", "resource_type", "external_id", name="uq_expense_doc_link"),
        )
    if "expense_review_decision" not in existing:
        op.create_table(
            "expense_review_decision",
            _uuid("id"),
            sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("target_period", sa.String(7), nullable=False, server_default=""),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    if "expense_profile_assignment" not in existing:
        op.create_table(
            "expense_profile_assignment",
            _uuid("id"),
            sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("profile_key", sa.String(100), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("matched_rule_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("transaction_id", "profile_key", name="uq_expense_profile_assignment"),
        )
    if "expense_match_rule" not in existing:
        op.create_table(
            "expense_match_rule",
            _uuid("id"),
            sa.Column("profile_key", sa.String(100), nullable=False, server_default=""),
            sa.Column("action", sa.String(32), nullable=False),
            sa.Column("match_field", sa.String(32), nullable=False),
            sa.Column("value_normalized", sa.Text(), nullable=False),
            sa.Column("value_original", sa.Text(), nullable=False, server_default=""),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    if "expense_supplier_link" not in existing:
        op.create_table(
            "expense_supplier_link",
            _uuid("id"),
            sa.Column("profile_key", sa.String(100), nullable=False, server_default=""),
            sa.Column("payee_normalized", sa.String(300), nullable=False, server_default=""),
            sa.Column("counterparty_iban", sa.String(64), nullable=False, server_default=""),
            sa.Column("label", sa.String(200), nullable=False, server_default=""),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    op.create_index("ix_expense_tx_value_date", "expense_transaction_snapshot", ["value_date"])
    op.create_index("ix_expense_review_tx", "expense_review_decision", ["transaction_id"])
    op.create_index("ix_expense_rule_profile", "expense_match_rule", ["profile_key"])


def downgrade() -> None:
    for name in (
        "ix_expense_rule_profile",
        "ix_expense_review_tx",
        "ix_expense_tx_value_date",
    ):
        op.drop_index(name)
    for table in (
        "expense_supplier_link",
        "expense_match_rule",
        "expense_profile_assignment",
        "expense_review_decision",
        "expense_document_link",
        "expense_transaction_snapshot",
        "expense_import_run",
    ):
        op.drop_table(table)
