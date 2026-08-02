"""Key-value settings stored in PostgreSQL (shared across PCs)."""
from __future__ import annotations

import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base


class SettingKV(Base):
    """Arbitrary JSON-serialized settings."""

    __tablename__ = "setting_kv"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
