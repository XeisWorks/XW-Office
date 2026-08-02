"""SQLAlchemy declarative base (PostgreSQL / Railway)."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata for all ORM models."""
