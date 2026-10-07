"""Persistence operations for the shared expense-review pipeline."""
from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.expense_pipeline import (
    ExpenseDocumentLink,
    ExpenseMatchRule,
    ExpenseProfileAssignment,
    ExpenseReviewDecision,
    ExpenseSupplierLink,
    ExpenseTransactionSnapshot,
)


class ExpensePipelineRepository:
    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def upsert_snapshot(self, values: dict[str, object]) -> ExpenseTransactionSnapshot:
        account_id = str(values["account_id"])
        external_id = str(values["external_id"])
        with self._scope() as session:
            row = session.scalar(
                select(ExpenseTransactionSnapshot).where(
                    ExpenseTransactionSnapshot.account_id == account_id,
                    ExpenseTransactionSnapshot.external_id == external_id,
                )
            )
            if row is None:
                row = ExpenseTransactionSnapshot(
                    account_id=account_id,
                    external_id=external_id,
                    value_date=values["value_date"],
                    amount=values["amount"],
                )
                session.add(row)
            for key, value in values.items():
                if key not in {"id", "account_id", "external_id"} and hasattr(row, key):
                    setattr(row, key, value)
            session.flush()
            session.refresh(row)
            return row

    def list_snapshots(
        self,
        *,
        start: datetime.date,
        end: datetime.date,
        direction: str = "outgoing",
    ) -> list[ExpenseTransactionSnapshot]:
        with self._scope() as session:
            stmt = (
                select(ExpenseTransactionSnapshot)
                .where(
                    ExpenseTransactionSnapshot.value_date >= start,
                    ExpenseTransactionSnapshot.value_date <= end,
                    ExpenseTransactionSnapshot.direction == direction,
                )
                .order_by(ExpenseTransactionSnapshot.value_date, ExpenseTransactionSnapshot.external_id)
            )
            return list(session.scalars(stmt).all())

    def add_assignment(
        self,
        *,
        transaction_id: uuid.UUID,
        profile_key: str,
        status: str,
        source: str,
        matched_rule_id: uuid.UUID | None = None,
    ) -> ExpenseProfileAssignment:
        with self._scope() as session:
            row = session.scalar(
                select(ExpenseProfileAssignment).where(
                    ExpenseProfileAssignment.transaction_id == transaction_id,
                    ExpenseProfileAssignment.profile_key == profile_key,
                )
            )
            if row is None:
                row = ExpenseProfileAssignment(
                    transaction_id=transaction_id,
                    profile_key=profile_key,
                    status=status,
                    source=source,
                    matched_rule_id=matched_rule_id,
                )
                session.add(row)
            else:
                row.status = status
                row.source = source
                row.matched_rule_id = matched_rule_id
                row.version += 1
            session.flush()
            session.refresh(row)
            return row

    def get_assignment(
        self, *, transaction_id: uuid.UUID, profile_key: str
    ) -> ExpenseProfileAssignment | None:
        with self._scope() as session:
            return session.scalar(
                select(ExpenseProfileAssignment).where(
                    ExpenseProfileAssignment.transaction_id == transaction_id,
                    ExpenseProfileAssignment.profile_key == profile_key,
                )
            )

    def add_rule(
        self,
        *,
        profile_key: str,
        action: str,
        match_field: str,
        value_normalized: str,
        value_original: str,
        source: str = "manual",
        priority: int = 100,
    ) -> ExpenseMatchRule:
        with self._scope() as session:
            existing = session.scalar(
                select(ExpenseMatchRule).where(
                    ExpenseMatchRule.profile_key == profile_key,
                    ExpenseMatchRule.action == action,
                    ExpenseMatchRule.match_field == match_field,
                    ExpenseMatchRule.value_normalized == value_normalized,
                )
            )
            if existing is not None:
                return existing
            row = ExpenseMatchRule(
                profile_key=profile_key,
                action=action,
                match_field=match_field,
                value_normalized=value_normalized,
                value_original=value_original,
                source=source,
                priority=priority,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    def list_rules(self, profile_key: str = "") -> list[ExpenseMatchRule]:
        with self._scope() as session:
            stmt = select(ExpenseMatchRule).where(ExpenseMatchRule.enabled.is_(True))
            if profile_key:
                stmt = stmt.where(
                    ExpenseMatchRule.profile_key.in_(("", profile_key))
                )
            return list(
                session.scalars(
                    stmt.order_by(ExpenseMatchRule.priority, ExpenseMatchRule.created_at)
                ).all()
            )

    def add_decision(
        self,
        *,
        transaction_id: uuid.UUID,
        status: str,
        note: str = "",
        target_period: str = "",
    ) -> ExpenseReviewDecision:
        with self._scope() as session:
            row = ExpenseReviewDecision(
                transaction_id=transaction_id,
                status=status,
                note=note,
                target_period=target_period,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    def add_document_link(
        self,
        *,
        transaction_id: uuid.UUID,
        resource_type: str,
        external_id: str,
        document_number: str = "",
    ) -> ExpenseDocumentLink:
        with self._scope() as session:
            row = session.scalar(
                select(ExpenseDocumentLink).where(
                    ExpenseDocumentLink.transaction_id == transaction_id,
                    ExpenseDocumentLink.resource_type == resource_type,
                    ExpenseDocumentLink.external_id == external_id,
                )
            )
            if row is None:
                row = ExpenseDocumentLink(
                    transaction_id=transaction_id,
                    resource_type=resource_type,
                    external_id=external_id,
                    document_number=document_number,
                )
                session.add(row)
            elif document_number:
                row.document_number = document_number
            session.flush()
            session.refresh(row)
            return row

    def list_document_links(self, transaction_id: uuid.UUID) -> list[ExpenseDocumentLink]:
        with self._scope() as session:
            return list(
                session.scalars(
                    select(ExpenseDocumentLink).where(
                        ExpenseDocumentLink.transaction_id == transaction_id
                    )
                ).all()
            )

    def add_supplier_link(
        self,
        *,
        profile_key: str,
        payee_normalized: str,
        counterparty_iban: str,
        label: str,
        url: str,
        source: str = "manual",
    ) -> ExpenseSupplierLink:
        with self._scope() as session:
            existing = session.scalar(
                select(ExpenseSupplierLink).where(
                    ExpenseSupplierLink.profile_key == profile_key,
                    ExpenseSupplierLink.payee_normalized == payee_normalized,
                    ExpenseSupplierLink.url == url,
                )
            )
            if existing is not None:
                return existing
            row = ExpenseSupplierLink(
                profile_key=profile_key,
                payee_normalized=payee_normalized,
                counterparty_iban=counterparty_iban,
                label=label,
                url=url,
                source=source,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    def list_supplier_links(
        self, *, profile_key: str = "", payee_normalized: str = "", iban: str = ""
    ) -> list[ExpenseSupplierLink]:
        with self._scope() as session:
            stmt = select(ExpenseSupplierLink).where(ExpenseSupplierLink.enabled.is_(True))
            if profile_key:
                stmt = stmt.where(ExpenseSupplierLink.profile_key.in_(("", profile_key)))
            if payee_normalized:
                stmt = stmt.where(ExpenseSupplierLink.payee_normalized == payee_normalized)
            if iban:
                stmt = stmt.where(ExpenseSupplierLink.counterparty_iban.in_(("", iban)))
            return list(session.scalars(stmt.order_by(ExpenseSupplierLink.created_at)).all())
