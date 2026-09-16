"""XW Product Hub — transactional outbox + sync foundation ORM models (PR10).

Schema per docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml. Nothing here calls Wix or
sevdesk — ``OutboxEvent`` rows are written by ``EditingService`` (PR09) in the same
transaction as each business change, and ``OutboxWorker`` (services/product_hub/
outbox_worker.py) claims/retries them, but there is no registered handler until PR11's
push adapter exists. ``SyncJob``/``SyncItem``/``SyncConflict``/``SyncCursor`` are schema
only in this PR — PR11 is the first real writer.
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

SYNC_DIRECTIONS = ("pull", "push", "reconcile")


class SyncJob(Base):
    """One run of a channel sync (pull/push/reconcile) — groups ``SyncItem`` rows."""

    __tablename__ = "sync_job"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyncItem(Base):
    """One entity's outcome within a :class:`SyncJob`."""

    __tablename__ = "sync_item"
    __table_args__ = (Index("ix_sync_item_sync_job_id", "sync_job_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sync_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sync_job.id", ondelete="CASCADE"), nullable=False
    )
    internal_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SyncConflict(Base):
    """A field-level drift between the hub and an external channel, pending resolution."""

    __tablename__ = "sync_conflict"
    __table_args__ = (
        Index("ix_sync_conflict_channel_resolved_at", "channel", "resolved_at"),
        Index("ix_sync_conflict_internal_entity_id", "internal_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    internal_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    field_name: Mapped[str] = mapped_column(String(160), nullable=False)
    hub_value: Mapped[object | None] = mapped_column(JSONVariant, nullable=True)
    external_value: Mapped[object | None] = mapped_column(JSONVariant, nullable=True)
    detected_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    external_updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


class SyncCursor(Base):
    """Per-channel/stream incremental-pull bookmark."""

    __tablename__ = "sync_cursor"
    __table_args__ = (UniqueConstraint("channel", "stream", name="uq_sync_cursor_channel_stream"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    stream: Mapped[str] = mapped_column(String(100), nullable=False)
    cursor_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExternalPayloadArchive(Base):
    """Debug/audit snapshot of a raw external payload — not a business master table."""

    __tablename__ = "external_payload_archive"
    __table_args__ = (
        Index(
            "ix_external_payload_archive_lookup",
            "channel",
            "entity_type",
            "external_id",
            "fetched_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONVariant, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxEvent(Base):
    """Transactional bridge from a canonical DB write to async external sync.

    Written by ``EditingService`` in the *same* transaction as the business change it
    describes (the build plan's "Outbox-Regel"), then claimed/retried by
    ``OutboxWorker`` — never written and processed in the same step, so a crash between
    "business write committed" and "external call made" can never lose the event.
    """

    __tablename__ = "outbox_event"
    __table_args__ = (Index("ix_outbox_event_processed_available", "processed_at", "available_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONVariant, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    available_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    claimed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "JSONVariant",
    "SYNC_DIRECTIONS",
    "SyncJob",
    "SyncItem",
    "SyncConflict",
    "SyncCursor",
    "ExternalPayloadArchive",
    "OutboxEvent",
]
