"""Encrypted API token storage (Fernet ciphertext)."""
from __future__ import annotations

import datetime

from sqlalchemy import DateTime, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class ApiSecret(Base):
    """One row per logical secret name (e.g. ``SEVDESK``, ``WIX``)."""

    __tablename__ = "api_secret"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
