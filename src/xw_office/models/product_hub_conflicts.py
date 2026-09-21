"""Persistent business-level conflict wizard models.

``SyncConflict`` remains the low-level channel drift signal.  These tables add the
durable workflow, decisions, previews and audit trail needed by the Product Hub UI.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base
from xw_office.models.product_hub import JSONVariant


CONFLICT_STATUSES = (
    "OPEN",
    "IN_PROGRESS",
    "WAITING",
    "PARTIALLY_RESOLVED",
    "RESOLVED",
    "IGNORED",
    "OBSOLETE",
)
CONFLICT_SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")


class ConflictScan(Base):
    __tablename__ = "conflict_scan"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scan_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_scope: Mapped[list[object]] = mapped_column(JSONVariant, default=list, nullable=False)
    product_scope: Mapped[dict[str, object]] = mapped_column(
        JSONVariant, default=dict, nullable=False
    )
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    products_scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    differences_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cases_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cases_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    auto_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)


class WixReconciliationDisposition(Base):
    """A deliberate, durable decision for a Wix-only catalog position.

    Wix catalog records do not necessarily belong in the Hub immediately.  This
    table keeps an explicit ``ignored`` or time-limited ``deferred`` decision
    separate from mappings, so an item cannot silently disappear simply because
    a user has seen it once.
    """

    __tablename__ = "wix_reconciliation_disposition"
    __table_args__ = (
        UniqueConstraint(
            "external_id", "variant_external_id", name="uq_wix_reconciliation_item"
        ),
        Index("ix_wix_reconciliation_disposition_due", "disposition", "deferred_until"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    # Empty string means the Wix parent product.  Keeping this non-null makes
    # the composite uniqueness portable between SQLite tests and PostgreSQL.
    variant_external_id: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    disposition: Mapped[str] = mapped_column(String(20), nullable=False)
    deferred_until: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConflictCase(Base):
    __tablename__ = "conflict_case"
    __table_args__ = (
        UniqueConstraint("dedupe_key", "occurrence", name="uq_conflict_case_dedupe_occurrence"),
        Index("ix_conflict_case_queue", "status", "severity", "priority_score"),
        Index("ix_conflict_case_product", "product_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="CASCADE")
    )
    origin_sync_conflict_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sync_conflict.id", ondelete="SET NULL"), index=True
    )
    conflict_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_to: Mapped[str | None] = mapped_column(String(160))
    resolution_type: Mapped[str | None] = mapped_column(String(40))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    source_scan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("conflict_scan.id", ondelete="SET NULL")
    )
    reopened_from_case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("conflict_case.id", ondelete="SET NULL")
    )
    dedupe_key: Mapped[str] = mapped_column(String(500), nullable=False)
    occurrence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    hub_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConflictField(Base):
    __tablename__ = "conflict_field"
    __table_args__ = (
        UniqueConstraint("conflict_case_id", "field_path", name="uq_conflict_field_case_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conflict_case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conflict_case.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_path: Mapped[str] = mapped_column(String(240), nullable=False)
    selected_value: Mapped[object | None] = mapped_column(JSONVariant)
    selected_source: Mapped[str | None] = mapped_column(String(20))
    resolution_type: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="OPEN", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConflictObservation(Base):
    __tablename__ = "conflict_observation"
    __table_args__ = (
        UniqueConstraint(
            "conflict_field_id", "source", "source_hash", name="uq_conflict_observation_snapshot"
        ),
        Index("ix_conflict_observation_field_source", "conflict_field_id", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conflict_field_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conflict_field.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_value: Mapped[object | None] = mapped_column(JSONVariant)
    normalized_value: Mapped[object | None] = mapped_column(JSONVariant)
    source_external_id: Mapped[str | None] = mapped_column(String(240))
    source_revision: Mapped[str | None] = mapped_column(String(240))
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConflictAction(Base):
    __tablename__ = "conflict_action"
    __table_args__ = (Index("ix_conflict_action_case", "conflict_case_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conflict_case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conflict_case.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(240))
    before_value: Mapped[object | None] = mapped_column(JSONVariant)
    after_value: Mapped[object | None] = mapped_column(JSONVariant)
    selected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PLANNED", nullable=False)
    outbox_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("outbox_event.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ResolutionRule(Base):
    __tablename__ = "resolution_rule"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scope: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)
    conditions: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)
    action: Mapped[dict[str, object]] = mapped_column(JSONVariant, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW", nullable=False)
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_from_case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("conflict_case.id", ondelete="SET NULL")
    )
    created_by: Mapped[str | None] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = [
    "ConflictAction",
    "ConflictCase",
    "ConflictField",
    "ConflictObservation",
    "ConflictScan",
    "ResolutionRule",
]
