"""XW Product Hub PR10: transactional outbox + sync foundation.

Additive from head 011_product_hub_row_versions. Schema-only per
docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml: ``outbox_event``, ``sync_job``,
``sync_item``, ``sync_conflict``, ``sync_cursor``, ``external_payload_archive``. No
existing table is touched.

Nothing pushes to Wix/sevdesk yet (that starts with PR11's feature-flagged push
adapter) and this migration does not touch ``SettingKV["inventory.products"]`` /
``inventory.stock_levels``. ``EditingService`` (PR09) writes ``outbox_event`` rows in
the same transaction as each business change per the build plan's outbox rule, but
nothing claims/processes them yet beyond the ``OutboxWorker`` this PR also adds —
there is no registered handler until PR11, so real events simply wait.

Revision ID: 012_product_hub_sync_outbox
Revises: 011_product_hub_row_versions
Create Date: 2026-09-16

"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012_product_hub_sync_outbox"
down_revision: Union[str, Sequence[str], None] = "011_product_hub_row_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk() -> sa.Column[uuid.UUID]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_job" not in existing_tables:
        op.create_table(
            "sync_job",
            _uuid_pk(),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("direction", sa.String(20), nullable=False),
            sa.Column("job_type", sa.String(80), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("requested_by", sa.String(160), nullable=True),
            sa.Column("error_summary", sa.Text(), nullable=True),
        )

    if "sync_item" not in existing_tables:
        op.create_table(
            "sync_item",
            _uuid_pk(),
            sa.Column(
                "sync_job_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("sync_job.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("internal_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("external_id", sa.String(240), nullable=True),
            sa.Column("action", sa.String(60), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_sync_item_sync_job_id", "sync_item", ["sync_job_id"])

    if "sync_conflict" not in existing_tables:
        op.create_table(
            "sync_conflict",
            _uuid_pk(),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("internal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("field_name", sa.String(160), nullable=False),
            sa.Column("hub_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("external_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("external_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolution", sa.String(60), nullable=True),
            sa.Column("resolved_by", sa.String(160), nullable=True),
        )
        op.create_index(
            "ix_sync_conflict_channel_resolved_at", "sync_conflict", ["channel", "resolved_at"]
        )
        op.create_index(
            "ix_sync_conflict_internal_entity_id", "sync_conflict", ["internal_entity_id"]
        )

    if "sync_cursor" not in existing_tables:
        op.create_table(
            "sync_cursor",
            _uuid_pk(),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("stream", sa.String(100), nullable=False),
            sa.Column("cursor_value", sa.Text(), nullable=True),
            sa.Column("last_seen_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint("channel", "stream", name="uq_sync_cursor_channel_stream"),
        )

    if "external_payload_archive" not in existing_tables:
        op.create_table(
            "external_payload_archive",
            _uuid_pk(),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("external_id", sa.String(240), nullable=True),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_external_payload_archive_lookup",
            "external_payload_archive",
            ["channel", "entity_type", "external_id", "fetched_at"],
        )

    if "outbox_event" not in existing_tables:
        op.create_table(
            "outbox_event",
            _uuid_pk(),
            sa.Column("aggregate_type", sa.String(80), nullable=False),
            sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("event_type", sa.String(120), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
        )
        op.create_index(
            "ix_outbox_event_processed_available",
            "outbox_event",
            ["processed_at", "available_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_outbox_event_processed_available", table_name="outbox_event")
    op.drop_table("outbox_event")
    op.drop_index("ix_external_payload_archive_lookup", table_name="external_payload_archive")
    op.drop_table("external_payload_archive")
    op.drop_table("sync_cursor")
    op.drop_index("ix_sync_conflict_internal_entity_id", table_name="sync_conflict")
    op.drop_index("ix_sync_conflict_channel_resolved_at", table_name="sync_conflict")
    op.drop_table("sync_conflict")
    op.drop_index("ix_sync_item_sync_job_id", table_name="sync_item")
    op.drop_table("sync_item")
    op.drop_table("sync_job")
