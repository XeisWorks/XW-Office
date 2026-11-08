"""Guided physical inventory count sessions and immutable count snapshots."""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class InventoryCountSession(Base):
    __tablename__ = "inventory_count_session"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    location_code: Mapped[str] = mapped_column(String(32), default="MAIN", nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    baseline_source_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    counted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InventoryCountLine(Base):
    __tablename__ = "inventory_count_line"
    __table_args__ = (
        UniqueConstraint("session_id", "variant_id", "location_code", name="uq_inventory_count_line_variant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inventory_count_session.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    location_code: Mapped[str] = mapped_column(String(32), nullable=False)
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    system_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    counted_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difference: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    movement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    counted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["InventoryCountLine", "InventoryCountSession"]
