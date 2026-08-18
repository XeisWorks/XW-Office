"""Persistence access for Lieferkorrekturen ("customer aftercare") cases."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime
from decimal import Decimal
import uuid
from collections.abc import Generator, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem

#: Statuses that still represent an "open" case, per spec §13's state diagram.
ACTIVE_STATUSES = ("PENDING_REVIEW", "WAITING", "TRIGGERED")


@dataclass(frozen=True)
class CustomerAftercareReservation:
    state: str
    case: CustomerAftercareCase


@dataclass(frozen=True)
class CustomerAftercareItemInput:
    role: str
    sku: str = ""
    name: str = ""
    quantity: int = 1
    sevdesk_part_id: str = ""
    source_unit_price: Decimal | None = None
    source_tax_rate: Decimal | None = None
    source_discount_percent: Decimal | None = None


class CustomerAftercareRepository:
    """Reserve/track Lieferkorrektur cases; idempotent on ``source_message_id``."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def _advisory_lock(self, session: Session, key: str) -> None:
        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": key},
            )

    # -- creation / idempotency -------------------------------------------------

    def reserve_case_by_message_id(
        self,
        *,
        source_message_id: str,
        source_thread_id: str = "",
        source_subject: str = "",
        ai_suggested_type: str = "",
        ai_confidence: Decimal | float | None = None,
        ai_payload_json: str = "{}",
        customer_email: str = "",
        customer_name: str = "",
        wix_contact_id: str = "",
        source_wix_order_id: str = "",
        source_wix_order_number: str = "",
        source_order_created_at: datetime.datetime | None = None,
    ) -> CustomerAftercareReservation:
        """Create a PENDING_REVIEW case for *source_message_id*, or return the existing one."""
        with self._scope() as session:
            self._advisory_lock(session, source_message_id)
            row = session.scalar(
                select(CustomerAftercareCase).where(
                    CustomerAftercareCase.source_message_id == source_message_id
                )
            )
            if row is not None:
                return CustomerAftercareReservation("already_exists", row)

            row = CustomerAftercareCase(
                source_message_id=source_message_id,
                source_thread_id=source_thread_id,
                source_subject=source_subject,
                ai_suggested_type=ai_suggested_type,
                case_type=ai_suggested_type,
                ai_confidence=ai_confidence,
                ai_payload_json=ai_payload_json,
                customer_email=customer_email,
                customer_name=customer_name,
                wix_contact_id=wix_contact_id,
                source_wix_order_id=source_wix_order_id,
                source_wix_order_number=source_wix_order_number,
                source_order_created_at=source_order_created_at,
                status="PENDING_REVIEW",
            )
            session.add(row)
            session.flush()
            return CustomerAftercareReservation("created", row)

    def add_items(
        self, case_id: uuid.UUID, items: Sequence[CustomerAftercareItemInput]
    ) -> list[CustomerAftercareItem]:
        with self._scope() as session:
            rows = [
                CustomerAftercareItem(
                    case_id=case_id,
                    role=item.role,
                    sku=item.sku,
                    name=item.name,
                    quantity=item.quantity,
                    sevdesk_part_id=item.sevdesk_part_id,
                    source_unit_price=item.source_unit_price,
                    source_tax_rate=item.source_tax_rate,
                    source_discount_percent=item.source_discount_percent,
                )
                for item in items
            ]
            session.add_all(rows)
            session.flush()
            return rows

    # -- reads --------------------------------------------------------------

    def get_case(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        with self._scope() as session:
            return session.get(CustomerAftercareCase, case_id)

    def get_case_by_message_id(self, source_message_id: str) -> CustomerAftercareCase | None:
        with self._scope() as session:
            return session.scalar(
                select(CustomerAftercareCase).where(
                    CustomerAftercareCase.source_message_id == source_message_id
                )
            )

    def get_items(self, case_id: uuid.UUID) -> list[CustomerAftercareItem]:
        with self._scope() as session:
            rows = session.scalars(
                select(CustomerAftercareItem)
                .where(CustomerAftercareItem.case_id == case_id)
                .order_by(CustomerAftercareItem.created_at)
            ).all()
            return list(rows)

    def list_by_statuses(self, statuses: Sequence[str]) -> list[CustomerAftercareCase]:
        with self._scope() as session:
            rows = session.scalars(
                select(CustomerAftercareCase)
                .where(CustomerAftercareCase.status.in_(statuses))
                .order_by(CustomerAftercareCase.created_at.desc())
            ).all()
            return list(rows)

    def count_by_statuses(self, statuses: Sequence[str]) -> int:
        with self._scope() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(CustomerAftercareCase)
                    .where(CustomerAftercareCase.status.in_(statuses))
                )
                or 0
            )

    def count_pending_review(self) -> int:
        return self.count_by_statuses(("PENDING_REVIEW",))

    def count_due(self, *, now: datetime.datetime | None = None) -> int:
        """Cases already TRIGGERED, plus WAITING cases whose ``due_at`` has passed."""
        now = now or datetime.datetime.now(datetime.timezone.utc)
        with self._scope() as session:
            triggered = int(
                session.scalar(
                    select(func.count())
                    .select_from(CustomerAftercareCase)
                    .where(CustomerAftercareCase.status == "TRIGGERED")
                )
                or 0
            )
            overdue_waiting = int(
                session.scalar(
                    select(func.count())
                    .select_from(CustomerAftercareCase)
                    .where(CustomerAftercareCase.status == "WAITING")
                    .where(CustomerAftercareCase.due_at.is_not(None))
                    .where(CustomerAftercareCase.due_at <= now)
                )
                or 0
            )
            return triggered + overdue_waiting

    def list_due_waiting_cases(
        self, *, now: datetime.datetime | None = None
    ) -> list[CustomerAftercareCase]:
        now = now or datetime.datetime.now(datetime.timezone.utc)
        with self._scope() as session:
            rows = session.scalars(
                select(CustomerAftercareCase)
                .where(CustomerAftercareCase.status == "WAITING")
                .where(CustomerAftercareCase.due_at.is_not(None))
                .where(CustomerAftercareCase.due_at <= now)
                .order_by(CustomerAftercareCase.due_at)
            ).all()
            return list(rows)

    def list_waiting_cases(self) -> list[CustomerAftercareCase]:
        return self.list_by_statuses(("WAITING",))

    # -- classification / lifecycle -----------------------------------------

    def confirm_classification(
        self,
        case_id: uuid.UUID,
        *,
        case_type: str,
        courtesy: bool,
        customer_type: str,
        wait_for_next_order: bool,
        due_at: datetime.datetime | None,
        trigger_now: bool,
        trigger_reason: str = "",
        invoice_required: bool = False,
        note: str = "",
    ) -> CustomerAftercareCase | None:
        """Apply the user's confirmed/edited type from the review popup (spec §4)."""
        with self._scope() as session:
            row = session.get(CustomerAftercareCase, case_id)
            if row is None:
                return None
            row.case_type = case_type
            row.courtesy = courtesy
            row.customer_type = customer_type
            row.wait_for_next_order = wait_for_next_order
            row.due_at = due_at
            row.invoice_required = invoice_required
            row.note = note
            row.classification_confirmed_at = func.now()
            if trigger_now:
                row.status = "TRIGGERED"
                row.triggered_at = func.now()
                row.trigger_reason = trigger_reason or "IMMEDIATE"
            else:
                row.status = "WAITING"
            session.flush()
            return row

    def try_transition_waiting_to_triggered(
        self,
        case_id: uuid.UUID,
        *,
        reason: str,
        trigger_wix_order_id: str = "",
        trigger_wix_order_number: str = "",
    ) -> CustomerAftercareCase | None:
        """Atomically move a WAITING case to TRIGGERED. Returns None if not eligible."""
        with self._scope() as session:
            self._advisory_lock(session, str(case_id))
            row = session.get(CustomerAftercareCase, case_id)
            if row is None or row.status != "WAITING":
                return None
            row.status = "TRIGGERED"
            row.triggered_at = func.now()
            row.trigger_reason = reason
            row.trigger_wix_order_id = trigger_wix_order_id
            row.trigger_wix_order_number = trigger_wix_order_number
            session.flush()
            return row

    def mark_ignored(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._mark(case_id, status="IGNORED")

    def mark_resolved(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._mark(case_id, status="RESOLVED", resolved_at=func.now())

    def mark_cancelled(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._mark(case_id, status="CANCELLED", cancelled_at=func.now())

    # -- invoicing ------------------------------------------------------------

    def mark_invoice_created(
        self, case_id: uuid.UUID, *, sevdesk_invoice_id: str, sevdesk_invoice_number: str
    ) -> CustomerAftercareCase | None:
        return self._mark(
            case_id,
            invoice_status="created",
            sevdesk_invoice_id=sevdesk_invoice_id,
            sevdesk_invoice_number=sevdesk_invoice_number,
            invoice_error="",
        )

    def mark_invoice_skipped(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._mark(case_id, invoice_status="skipped", invoice_error="")

    def mark_invoice_failed(
        self, case_id: uuid.UUID, *, error_message: str
    ) -> CustomerAftercareCase | None:
        return self._mark(
            case_id, invoice_status="failed", invoice_error=str(error_message or "")[:2000]
        )

    def _mark(self, case_id: uuid.UUID, **values: object) -> CustomerAftercareCase | None:
        with self._scope() as session:
            row = session.get(CustomerAftercareCase, case_id)
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            session.flush()
            return row
