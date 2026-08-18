"""Lieferkorrekturen ("customer aftercare") case and line-item persistence."""
from __future__ import annotations

import datetime
from decimal import Decimal
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class CustomerAftercareCase(Base):
    """One delivery-correction case: wrong/missing items, trigger state, invoicing state."""

    __tablename__ = "customer_aftercare_case"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    case_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="PENDING_REVIEW", nullable=False, index=True
    )

    source_message_id: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    source_thread_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    source_subject: Mapped[str] = mapped_column(Text, default="", nullable=False)

    ai_suggested_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    ai_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    ai_payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    classification_confirmed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    customer_type: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    wix_contact_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    customer_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    customer_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    source_wix_order_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source_wix_order_number: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source_order_created_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    courtesy: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    wait_for_next_order: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    due_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    triggered_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger_reason: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    trigger_wix_order_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    trigger_wix_order_number: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    invoice_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    invoice_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    sevdesk_invoice_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    sevdesk_invoice_number: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    invoice_error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CustomerAftercareItem(Base):
    """One line item on a :class:`CustomerAftercareCase` (wrong/missing/corrected/shipping)."""

    __tablename__ = "customer_aftercare_item"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customer_aftercare_case.id"), index=True, nullable=False
    )

    role: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    sku: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sevdesk_part_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    source_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    source_discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
