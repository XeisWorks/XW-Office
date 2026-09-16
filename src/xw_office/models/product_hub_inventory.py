"""XW Product Hub — Inventory V2 ledger ORM models (PR13/PR14, shadow mode).

Schema per docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml. Nothing here is read by
the legacy print/fulfillment paths yet — see ``services/product_hub/inventory.py``'s
module docstring for the shadow-mode scope and what's deliberately deferred.
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base

INVENTORY_REASONS = (
    "import_baseline",
    "sale",
    "print_run",
    "return",
    "damage",
    "manual_adjustment",
    "recount",
)
ALERT_TYPES = ("low_stock", "out_of_stock", "sync_drift")
ALERT_STATUSES = ("open", "acknowledged", "resolved")


class InventoryLocation(Base):
    __tablename__ = "inventory_location"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class InventoryStock(Base):
    """Materialized current stock — changed only through ``InventoryRepository.
    record_movement``'s ledger transaction, never directly."""

    __tablename__ = "inventory_stock"
    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="ck_inventory_stock_on_hand_non_negative"),
        CheckConstraint("reserved >= 0", name="ck_inventory_stock_reserved_non_negative"),
    )

    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="RESTRICT"), primary_key=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inventory_location.id", ondelete="RESTRICT"), primary_key=True
    )
    on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reorder_point: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target_stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    default_reprint_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


class InventoryMovement(Base):
    """Immutable stock ledger entry. No update/delete through application paths —
    a correction is always a new, compensating movement."""

    __tablename__ = "inventory_movement"
    __table_args__ = (
        Index("ix_inventory_movement_variant_location", "variant_id", "location_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=False
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(240), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(240), unique=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    on_hand_after: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str | None] = mapped_column(String(160), nullable=True)
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InventoryAlert(Base):
    """Stateful threshold alert — deduplicates XW-Flow tasks (PR14). At most one
    OPEN alert per (variant, location, type); enforced by a Postgres partial unique
    index in the migration, and defensively in the repository for SQLite tests."""

    __tablename__ = "inventory_alert"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_triggered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_triggered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    acknowledged_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    xw_flow_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    xw_flow_client_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


__all__ = [
    "INVENTORY_REASONS",
    "ALERT_TYPES",
    "ALERT_STATUSES",
    "InventoryLocation",
    "InventoryStock",
    "InventoryMovement",
    "InventoryAlert",
]
