"""Audit and idempotency state for Post Label Center submissions."""
from __future__ import annotations

import datetime
from decimal import Decimal
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Uuid, func
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
    response_collo_codes_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
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


class PlcParcelManifest(Base):
    """Declared contents of one physical parcel in a PLC shipment."""

    __tablename__ = "plc_parcel_manifest"
    __table_args__ = (UniqueConstraint("shipment_id", "package_number", name="uq_plc_parcel_shipment_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("plc_shipment.id"), nullable=False, index=True)
    package_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parcel_reference: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    contents_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    tracking_code: Mapped[str] = mapped_column(String(100), default="", nullable=False, index=True)
    code_assignment: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    confirmed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    packing_pdf_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class PlcTrackingEvent(Base):
    """Event copied from an original Austrian Post tracking XML feed."""

    __tablename__ = "plc_tracking_event"
    __table_args__ = (UniqueConstraint("tracking_code", "event_id", name="uq_plc_tracking_code_event"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tracking_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_reason: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    event_postal_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    event_city: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    event_country: Mapped[str] = mapped_column(String(2), default="", nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
