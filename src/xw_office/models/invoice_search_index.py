"""Shared sevDesk invoice search index (one row per invoice)."""
from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class InvoiceSearchIndex(Base):
    """Normalized, searchable copy of a sevDesk invoice summary."""

    __tablename__ = "invoice_search_index"

    invoice_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    invoice_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    search_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_invoice_search_index_invoice_number", "invoice_number"),
        Index("ix_invoice_search_index_synced_at", "synced_at"),
    )
