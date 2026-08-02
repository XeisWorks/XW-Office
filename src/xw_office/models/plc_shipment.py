"""Audit and idempotency state for Post Label Center submissions."""
from __future__ import annotations

import datetime
from decimal import Decimal
import uuid

from sqlalchemy import DateTime, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class PlcShipment(Base):
    """One submitted PLC shipment, without retaining address or label contents."""

    __tablename__ = "plc_shipment"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    invoice_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    reference: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    mode: Mapped[str] = mapped_column(String(8), default="LIVE", nullable=False)
    transport: Mapped[str] = mapped_column(String(32), default="webservice", nullable=False)
    product_code: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    country_iso2: Mapped[str] = mapped_column(String(2), default="", nullable=False)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    price_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="sending", nullable=False)
    tracking_codes_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    label_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    print_job_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    printed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
