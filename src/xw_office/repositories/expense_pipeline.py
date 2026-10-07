"""Persistence operations for the shared expense-review pipeline."""
from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.expense_pipeline import (
    ExpenseDocumentLink,
    ExpenseDocumentScan,
    ExpenseImportRun,
    ExpenseMatchRule,
    ExpensePosition,
    ExpensePositionAssignment,
    ExpensePositionRule,
    ExpenseProfileAssignment,
    ExpensePurposeRule,
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
            stmt = select(ExpenseTransactionSnapshot).where(
                ExpenseTransactionSnapshot.value_date >= start,
                ExpenseTransactionSnapshot.value_date <= end,
            )
            if direction:
                stmt = stmt.where(ExpenseTransactionSnapshot.direction == direction)
            stmt = stmt.order_by(ExpenseTransactionSnapshot.value_date, ExpenseTransactionSnapshot.external_id)
            return list(session.scalars(stmt).all())

    def record_import_run(
        self,
        *,
        account_id: str,
        account_name: str,
        period_start: datetime.date,
        period_end: datetime.date,
        status: str,
        sevdesk_last_sync_at: datetime.datetime | None,
        transaction_count: int,
        linked_count: int,
        error_count: int = 0,
        error_text: str = "",
    ) -> ExpenseImportRun:
        with self._scope() as session:
            row = ExpenseImportRun(
                account_id=account_id,
                account_name=account_name,
                period_start=period_start,
                period_end=period_end,
                status=status,
                sevdesk_last_sync_at=sevdesk_last_sync_at,
                finished_at=datetime.datetime.now(datetime.UTC),
                transaction_count=transaction_count,
                linked_count=linked_count,
                error_count=error_count,
                error_text=error_text,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    def has_complete_import_run(
        self, *, account_id: str, period_start: datetime.date, period_end: datetime.date
    ) -> bool:
        with self._scope() as session:
            return (
                session.scalar(
                    select(ExpenseImportRun.id)
                    .where(
                        ExpenseImportRun.account_id == account_id,
                        ExpenseImportRun.period_start == period_start,
                        ExpenseImportRun.period_end == period_end,
                        ExpenseImportRun.status == "complete",
                    )
                    .order_by(ExpenseImportRun.finished_at.desc())
                    .limit(1)
                )
                is not None
            )

    def list_positions(self, *, enabled_only: bool = True) -> list[ExpensePosition]:
        with self._scope() as session:
            stmt = select(ExpensePosition)
            if enabled_only:
                stmt = stmt.where(ExpensePosition.enabled.is_(True))
            return list(session.scalars(stmt.order_by(ExpensePosition.sort_order, ExpensePosition.key)).all())

    def ensure_positions(self, defaults: list[dict[str, object]]) -> None:
        """Insert missing defaults without overwriting user-maintained values."""
        with self._scope() as session:
            existing = set(session.scalars(select(ExpensePosition.key)).all())
            for values in defaults:
                key = str(values["key"])
                if key in existing:
                    continue
                session.add(ExpensePosition(**values))
            session.flush()

    def upsert_position(
        self,
        *,
        key: str,
        label: str,
        initials: str,
        color: str,
        sort_order: int = 100,
        enabled: bool = True,
    ) -> ExpensePosition:
        normalized_key = key.strip().lower()
        if not normalized_key:
            raise ValueError("Positionsschlüssel fehlt")
        with self._scope() as session:
            row = session.get(ExpensePosition, normalized_key)
            if row is None:
                row = ExpensePosition(key=normalized_key, label=label, initials=initials, color=color)
                session.add(row)
            row.label = label.strip()
            row.initials = initials.strip().upper()
            row.color = color.strip()
            row.sort_order = int(sort_order)
            row.enabled = bool(enabled)
            session.flush()
            session.refresh(row)
            return row

    def get_position_assignment(
        self, *, transaction_id: uuid.UUID
    ) -> ExpensePositionAssignment | None:
        with self._scope() as session:
            return session.scalar(
                select(ExpensePositionAssignment).where(
                    ExpensePositionAssignment.transaction_id == transaction_id
                )
            )

    def list_position_assignments_for_transactions(
        self, transaction_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, ExpensePositionAssignment]:
        if not transaction_ids:
            return {}
        with self._scope() as session:
            rows = list(
                session.scalars(
                    select(ExpensePositionAssignment).where(
                        ExpensePositionAssignment.transaction_id.in_(transaction_ids)
                    )
                ).all()
            )
        return {row.transaction_id: row for row in rows}

    def assign_position(
        self,
        *,
        transaction_id: uuid.UUID,
        position_key: str,
        source: str,
        matched_rule_id: uuid.UUID | None = None,
    ) -> ExpensePositionAssignment:
        with self._scope() as session:
            row = session.scalar(
                select(ExpensePositionAssignment).where(
                    ExpensePositionAssignment.transaction_id == transaction_id
                )
            )
            if row is None:
                row = ExpensePositionAssignment(
                    transaction_id=transaction_id,
                    position_key=position_key,
                    source=source,
                    matched_rule_id=matched_rule_id,
                )
                session.add(row)
            else:
                row.position_key = position_key
                row.source = source
                row.matched_rule_id = matched_rule_id
                row.version += 1
            session.flush()
            session.refresh(row)
            return row

    def add_position_rule(
        self,
        *,
        position_key: str,
        label: str = "",
        payee_normalized: str = "",
        counterparty_iban: str = "",
        purpose_contains: str = "",
        source: str = "manual",
        priority: int = 100,
    ) -> ExpensePositionRule:
        if not any((payee_normalized, counterparty_iban, purpose_contains)):
            raise ValueError("Eine Regel benötigt mindestens ein Kriterium")
        with self._scope() as session:
            existing = session.scalar(
                select(ExpensePositionRule).where(
                    ExpensePositionRule.position_key == position_key,
                    ExpensePositionRule.payee_normalized == payee_normalized,
                    ExpensePositionRule.counterparty_iban == counterparty_iban,
                    ExpensePositionRule.purpose_contains == purpose_contains,
                )
            )
            if existing is not None:
                existing.enabled = True
                if label:
                    existing.label = label
                session.flush()
                session.refresh(existing)
                return existing
            row = ExpensePositionRule(
                position_key=position_key,
                label=label,
                payee_normalized=payee_normalized,
                counterparty_iban=counterparty_iban,
                purpose_contains=purpose_contains,
                source=source,
                priority=priority,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    def list_position_rules(self, *, enabled_only: bool = True) -> list[ExpensePositionRule]:
        with self._scope() as session:
            stmt = select(ExpensePositionRule)
            if enabled_only:
                stmt = stmt.where(ExpensePositionRule.enabled.is_(True))
            return list(session.scalars(stmt.order_by(ExpensePositionRule.priority, ExpensePositionRule.created_at)).all())

    def set_position_rule_enabled(self, rule_id: uuid.UUID, enabled: bool) -> bool:
        with self._scope() as session:
            row = session.get(ExpensePositionRule, rule_id)
            if row is None:
                return False
            row.enabled = bool(enabled)
            session.flush()
            return True

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

    def list_all_supplier_links(self) -> list[ExpenseSupplierLink]:
        with self._scope() as session:
            return list(
                session.scalars(
                    select(ExpenseSupplierLink).order_by(
                        ExpenseSupplierLink.label, ExpenseSupplierLink.created_at
                    )
                ).all()
            )

    def update_supplier_link(
        self,
        *,
        link_id: uuid.UUID,
        payee_normalized: str,
        counterparty_iban: str,
        label: str,
        url: str,
    ) -> ExpenseSupplierLink | None:
        with self._scope() as session:
            row = session.get(ExpenseSupplierLink, link_id)
            if row is None:
                return None
            row.payee_normalized = payee_normalized
            row.counterparty_iban = counterparty_iban
            row.label = label
            row.url = url
            session.flush()
            session.refresh(row)
            return row

    def list_purpose_rules(self, *, enabled_only: bool = False) -> list[ExpensePurposeRule]:
        with self._scope() as session:
            stmt = select(ExpensePurposeRule)
            if enabled_only:
                stmt = stmt.where(ExpensePurposeRule.enabled.is_(True))
            return list(
                session.scalars(
                    stmt.order_by(ExpensePurposeRule.priority, ExpensePurposeRule.created_at)
                ).all()
            )

    def add_purpose_rule(
        self, *, payee_normalized: str, remove_text: str, label: str = ""
    ) -> ExpensePurposeRule:
        with self._scope() as session:
            existing = session.scalar(
                select(ExpensePurposeRule).where(
                    ExpensePurposeRule.payee_normalized == payee_normalized,
                    ExpensePurposeRule.remove_text == remove_text,
                )
            )
            if existing is not None:
                return existing
            row = ExpensePurposeRule(
                payee_normalized=payee_normalized,
                remove_text=remove_text,
                label=label,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    def update_purpose_rule(
        self, *, rule_id: uuid.UUID, payee_normalized: str, remove_text: str, label: str
    ) -> ExpensePurposeRule | None:
        with self._scope() as session:
            row = session.get(ExpensePurposeRule, rule_id)
            if row is None:
                return None
            row.payee_normalized = payee_normalized
            row.remove_text = remove_text
            row.label = label
            session.flush()
            session.refresh(row)
            return row

    def set_purpose_rule_enabled(self, rule_id: uuid.UUID, enabled: bool) -> bool:
        with self._scope() as session:
            row = session.get(ExpensePurposeRule, rule_id)
            if row is None:
                return False
            row.enabled = bool(enabled)
            session.flush()
            return True

    def list_assignments_for_transactions(
        self, *, transaction_ids: list[uuid.UUID], profile_key: str
    ) -> dict[uuid.UUID, ExpenseProfileAssignment]:
        if not transaction_ids or not profile_key:
            return {}
        with self._scope() as session:
            rows = list(
                session.scalars(
                    select(ExpenseProfileAssignment).where(
                        ExpenseProfileAssignment.transaction_id.in_(transaction_ids),
                        ExpenseProfileAssignment.profile_key == profile_key,
                    )
                ).all()
            )
        return {row.transaction_id: row for row in rows}

    def list_document_links_for_transactions(
        self, transaction_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[ExpenseDocumentLink]]:
        if not transaction_ids:
            return {}
        with self._scope() as session:
            rows = list(
                session.scalars(
                    select(ExpenseDocumentLink).where(
                        ExpenseDocumentLink.transaction_id.in_(transaction_ids)
                    )
                ).all()
            )
        result: dict[uuid.UUID, list[ExpenseDocumentLink]] = {}
        for row in rows:
            result.setdefault(row.transaction_id, []).append(row)
        return result

    def list_document_scan_fingerprints(self) -> dict[tuple[str, str], str]:
        with self._scope() as session:
            return {
                (row.resource_type, row.external_id): row.fingerprint
                for row in session.scalars(select(ExpenseDocumentScan)).all()
            }

    def list_unlinked_document_scan_keys(self) -> set[tuple[str, str]]:
        """Return cached documents that have never yielded a bank-link."""
        with self._scope() as session:
            rows = session.execute(
                select(ExpenseDocumentScan.resource_type, ExpenseDocumentScan.external_id)
                .outerjoin(
                    ExpenseDocumentLink,
                    and_(
                        ExpenseDocumentLink.resource_type == ExpenseDocumentScan.resource_type,
                        ExpenseDocumentLink.external_id == ExpenseDocumentScan.external_id,
                    ),
                )
                .where(ExpenseDocumentLink.id.is_(None))
            ).all()
        return {(str(resource_type), str(external_id)) for resource_type, external_id in rows}

    def upsert_document_scan(
        self, *, resource_type: str, external_id: str, fingerprint: str
    ) -> ExpenseDocumentScan:
        with self._scope() as session:
            row = session.scalar(
                select(ExpenseDocumentScan).where(
                    ExpenseDocumentScan.resource_type == resource_type,
                    ExpenseDocumentScan.external_id == external_id,
                )
            )
            if row is None:
                row = ExpenseDocumentScan(
                    resource_type=resource_type,
                    external_id=external_id,
                    fingerprint=fingerprint,
                )
                session.add(row)
            else:
                row.fingerprint = fingerprint
                row.scanned_at = datetime.datetime.now(datetime.UTC)
            session.flush()
            session.refresh(row)
            return row

    def delete_document_links_for_document(self, *, resource_type: str, external_id: str) -> int:
        with self._scope() as session:
            result = session.execute(
                delete(ExpenseDocumentLink).where(
                    ExpenseDocumentLink.resource_type == resource_type,
                    ExpenseDocumentLink.external_id == external_id,
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)

    def set_supplier_link_enabled(self, link_id: uuid.UUID, enabled: bool) -> bool:
        with self._scope() as session:
            row = session.get(ExpenseSupplierLink, link_id)
            if row is None:
                return False
            row.enabled = bool(enabled)
            session.flush()
            return True
