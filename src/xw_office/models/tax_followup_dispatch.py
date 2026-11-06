"""Auditable, idempotent tax follow-up mail attempts."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class TaxFollowupDispatch(Base):
    __tablename__ = "tax_followup_dispatches"
    __table_args__ = (
        UniqueConstraint(
            "filing_kind", "period", "calculation_hash", "recipient_kind",
            name="uq_tax_followup_dispatch_identity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dispatch_key: Mapped[str] = mapped_column(String(220), unique=True, index=True, nullable=False)
    filing_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    calculation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message_correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attachment_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
