"""Ausgaben-Check ignore rules and period shifts.

Real tables instead of the legacy flat JSON files, so ignore rules and
period reassignments sync across every XeisWorks PC like everything else
in this schema.
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from xw_studio.models.base import Base


class ExpenseIgnoreRule(Base):
    """A user-defined 'always ignore transactions like this' rule.

    ``pattern_normalized`` is compared against normalized transaction text
    with fuzzy matching (see :mod:`xw_studio.core.fuzzy_match`), so a
    recurring payment whose reference number changes each month is still
    recognized.
    """

    __tablename__ = "expense_ignore_rule"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mandant: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    pattern_original: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pattern_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="forever", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExpenseShiftEntry(Base):
    """A manual reassignment of one transaction into a different reporting period."""

    __tablename__ = "expense_shift_entry"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mandant: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    transaction_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    source_period: Mapped[str] = mapped_column(String(7), nullable=False)
    target_period: Mapped[str] = mapped_column(String(7), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
