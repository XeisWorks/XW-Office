"""Idempotent invoice/credit-note position bookings for inventory movements."""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class InventoryDocumentBooking(Base):
    """Cumulative quantity already applied for one exact document position.

    ``quantity_applied`` is signed: sales are negative and credit/return lines are
    positive.  A later poll compares the newly observed target with this value and
    applies only the difference.
    """

    __tablename__ = "inventory_document_booking"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "position_key",
            "movement_kind",
            name="uq_inventory_document_booking_position",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    position_key: Mapped[str] = mapped_column(String(160), nullable=False)
    movement_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variant.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_applied: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_revision: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    last_idempotency_key: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    original_document_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    original_position_key: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = ["InventoryDocumentBooking"]
