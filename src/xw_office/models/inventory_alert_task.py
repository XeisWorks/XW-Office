"""Durable, deduplicated Graph task mails for inventory alerts."""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class InventoryAlertTask(Base):
    __tablename__ = "inventory_alert_task"
    __table_args__ = (UniqueConstraint("alert_id", name="uq_inventory_alert_task_alert"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inventory_alert.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(320), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["InventoryAlertTask"]
