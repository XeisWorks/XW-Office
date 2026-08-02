"""Persistence for Ausgaben-Check ignore rules and period shift entries."""
from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.expense_check import ExpenseIgnoreRule, ExpenseShiftEntry


class ExpenseCheckRepository:
    """Read/write Ausgaben-Check ignore rules and period shift entries."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def list_ignore_rules(self, mandant: str = "") -> list[ExpenseIgnoreRule]:
        with self._scope() as session:
            stmt = select(ExpenseIgnoreRule)
            if mandant:
                stmt = stmt.where(ExpenseIgnoreRule.mandant == mandant)
            return list(session.scalars(stmt.order_by(ExpenseIgnoreRule.created_at)).all())

    def add_ignore_rule(
        self,
        *,
        mandant: str,
        pattern_original: str,
        pattern_normalized: str,
        scope: str,
    ) -> ExpenseIgnoreRule:
        with self._scope() as session:
            rule = ExpenseIgnoreRule(
                mandant=mandant,
                pattern_original=pattern_original,
                pattern_normalized=pattern_normalized,
                scope=scope,
            )
            session.add(rule)
            session.flush()
            session.refresh(rule)
            return rule

    def remove_ignore_rule(self, rule_id: uuid.UUID) -> bool:
        with self._scope() as session:
            row = session.get(ExpenseIgnoreRule, rule_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def list_shift_entries(self, mandant: str = "") -> list[ExpenseShiftEntry]:
        with self._scope() as session:
            stmt = select(ExpenseShiftEntry)
            if mandant:
                stmt = stmt.where(ExpenseShiftEntry.mandant == mandant)
            return list(session.scalars(stmt.order_by(ExpenseShiftEntry.created_at)).all())

    def add_shift_entry(
        self,
        *,
        mandant: str,
        transaction_ref: str,
        source_period: str,
        target_period: str,
        note: str = "",
    ) -> ExpenseShiftEntry:
        with self._scope() as session:
            entry = ExpenseShiftEntry(
                mandant=mandant,
                transaction_ref=transaction_ref,
                source_period=source_period,
                target_period=target_period,
                note=note,
            )
            session.add(entry)
            session.flush()
            session.refresh(entry)
            return entry
