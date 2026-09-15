"""Persistent state for manually controlled digital license deliveries."""
from __future__ import annotations

import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class DigitalLicenseFulfillment(Base):
    """One idempotent fulfillment workflow per sevDesk invoice."""

    __tablename__ = "digital_license_fulfillment"

    invoice_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    order_reference: Mapped[str] = mapped_column(String(128), nullable=False, index=True, server_default="")
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True, server_default="PENDING_DECISION")
    licensed_files_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    invoice_attachment_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    outlook_entry_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    outlook_store_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    invoice_finalized_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_processed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deferred_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    draft_created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wix_fulfilled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
