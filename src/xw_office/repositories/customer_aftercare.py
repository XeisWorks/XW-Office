"""Persistence access for Lieferkorrekturen ("customer aftercare") cases."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime
import json
from decimal import Decimal
import uuid
from collections.abc import Generator, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem

#: Statuses that still represent an "open" case, per spec §13's state diagram.
ACTIVE_STATUSES = ("PENDING_REVIEW", "WAITING", "TRIGGERED", "SNOOZED")
REDELIVERY_CASE_TYPES = (
    "MANUAL_REDELIVERY",
    "B2B_WRONG_DELIVERY",
    "B2B_MISSING_ITEMS",
    "B2C_WRONG_DELIVERY",
)


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
    source_kind: str = ""
    source_item_id: str = ""
    parent_sku: str = ""
    component_id: str = ""
    origin_invoice_number: str = ""
    origin_order_number: str = ""
    note: str = ""


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
        source_invoice_id: str = "",
        source_invoice_number: str = "",
        source_invoice_date: str = "",
        source_mail_sender: str = "",
        source_mail_body: str = "",
        sevdesk_contact_id: str = "",
        address_lines: Sequence[str] = (),
        address_source: str = "",
        shipping_mode: str = "WAIT_NEXT_ORDER_OR_DEADLINE",
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
                source_invoice_id=str(source_invoice_id or "").strip(),
                source_invoice_number=str(source_invoice_number or "").strip(),
                source_invoice_date=str(source_invoice_date or "").strip(),
                source_mail_sender=str(source_mail_sender or "").strip(),
                source_mail_body=str(source_mail_body or "").strip(),
                sevdesk_contact_id=str(sevdesk_contact_id or "").strip(),
                address_lines_json=json.dumps(
                    [str(item).strip() for item in address_lines if str(item).strip()],
                    ensure_ascii=False,
                ),
                address_source=str(address_source or "").strip(),
                shipping_mode=str(shipping_mode or "WAIT_NEXT_ORDER_OR_DEADLINE").strip(),
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
                    source_kind=item.source_kind,
                    source_item_id=item.source_item_id,
                    parent_sku=item.parent_sku,
                    component_id=item.component_id,
                    origin_invoice_number=item.origin_invoice_number,
                    origin_order_number=item.origin_order_number,
                    note=item.note,
                )
                for item in items
            ]
            session.add_all(rows)
            session.flush()
            return rows

    def create_invoice_case(
        self,
        *,
        invoice_id: str,
        invoice_number: str,
        invoice_date: str = "",
        order_number: str = "",
        wix_order_id: str = "",
        customer_name: str = "",
        customer_email: str = "",
        sevdesk_contact_id: str = "",
        wix_contact_id: str = "",
        address_lines: Sequence[str] = (),
        address_source: str = "",
        items: Sequence[CustomerAftercareItemInput] = (),
        note: str = "",
        shipping_mode: str = "WAIT_NEXT_ORDER_OR_DEADLINE",
        ai_payload_json: str = "",
    ) -> CustomerAftercareReservation:
        """Create an idempotent case directly from one sevDesk invoice."""
        invoice_key = str(invoice_id or invoice_number or "").strip()
        if not invoice_key:
            raise ValueError("invoice_id oder invoice_number fehlt")
        base_source_id = f"invoice-redelivery:{invoice_key}"
        existing = self.get_case_by_message_id(base_source_id)
        if existing is not None and existing.status in ACTIVE_STATUSES:
            return CustomerAftercareReservation("already_exists", existing)
        source_message_id = (
            base_source_id if existing is None else f"{base_source_id}:{uuid.uuid4()}"
        )
        reservation = self.reserve_case_by_message_id(
            source_message_id=source_message_id,
            source_subject=f"Nachlieferung zu {invoice_number or invoice_key}",
            ai_suggested_type="MANUAL_REDELIVERY",
            ai_payload_json=ai_payload_json
            or json.dumps({"source": "invoice_action"}, ensure_ascii=False),
            customer_email=customer_email,
            customer_name=customer_name,
            wix_contact_id=wix_contact_id,
            source_wix_order_number=order_number,
            source_wix_order_id=wix_order_id,
            source_invoice_id=invoice_id,
            source_invoice_number=invoice_number,
            source_invoice_date=invoice_date,
            sevdesk_contact_id=sevdesk_contact_id,
            address_lines=address_lines,
            address_source=address_source,
            shipping_mode=shipping_mode,
        )
        if reservation.state == "created":
            self.replace_items(reservation.case.id, items)
            self.update_case_details(reservation.case.id, note=note, shipping_mode=shipping_mode)
        return reservation

    def replace_items(
        self, case_id: uuid.UUID, items: Sequence[CustomerAftercareItemInput]
    ) -> list[CustomerAftercareItem]:
        with self._scope() as session:
            session.query(CustomerAftercareItem).filter(
                CustomerAftercareItem.case_id == case_id
            ).delete(synchronize_session=False)
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
                    source_kind=item.source_kind,
                    source_item_id=item.source_item_id,
                    parent_sku=item.parent_sku,
                    component_id=item.component_id,
                    origin_invoice_number=item.origin_invoice_number,
                    origin_order_number=item.origin_order_number,
                    note=item.note,
                )
                for item in items
            ]
            session.add_all(rows)
            session.flush()
            return rows

    def update_case_details(
        self,
        case_id: uuid.UUID,
        *,
        note: str | None = None,
        address_lines: Sequence[str] | None = None,
        address_source: str | None = None,
        shipping_mode: str | None = None,
    ) -> CustomerAftercareCase | None:
        with self._scope() as session:
            row = session.get(CustomerAftercareCase, case_id)
            if row is None:
                return None
            if note is not None:
                row.note = str(note or "").strip()
            if address_lines is not None:
                row.address_lines_json = json.dumps(
                    [str(item).strip() for item in address_lines if str(item).strip()],
                    ensure_ascii=False,
                )
            if address_source is not None:
                row.address_source = str(address_source or "").strip()
            if shipping_mode is not None:
                row.shipping_mode = str(shipping_mode or "").strip()
            session.flush()
            return row

    def list_matching_cases(
        self,
        *,
        sevdesk_contact_id: str = "",
        wix_contact_id: str = "",
        customer_email: str = "",
    ) -> list[CustomerAftercareCase]:
        """Return unprinted cases matching stable customer identifiers."""
        with self._scope() as session:
            candidates = session.scalars(
                select(CustomerAftercareCase)
                .where(CustomerAftercareCase.status.in_(("WAITING", "TRIGGERED")))
                .where(CustomerAftercareCase.case_type.in_(REDELIVERY_CASE_TYPES))
                .where(CustomerAftercareCase.delivery_note_printed_at.is_(None))
                .order_by(CustomerAftercareCase.created_at)
            ).all()
            sevdesk = str(sevdesk_contact_id or "").strip()
            wix = str(wix_contact_id or "").strip()
            email = str(customer_email or "").strip().casefold()
            return [
                row
                for row in candidates
                if self._customer_matches(
                    row, sevdesk_contact_id=sevdesk, wix_contact_id=wix, customer_email=email
                )
            ]

    def claim_for_invoice(
        self,
        *,
        invoice_id: str,
        invoice_number: str,
        sevdesk_contact_id: str = "",
        wix_contact_id: str = "",
        customer_email: str = "",
        wix_order_id: str = "",
        wix_order_number: str = "",
        invoice_date: str = "",
    ) -> list[CustomerAftercareCase]:
        """Atomically bind all matching, not-yet-printed cases to a new invoice."""
        key = f"aftercare-claim:{sevdesk_contact_id}:{wix_contact_id}:{customer_email}"
        with self._scope() as session:
            self._advisory_lock(session, key)
            candidates = session.scalars(
                select(CustomerAftercareCase)
                .where(CustomerAftercareCase.status.in_(("WAITING", "TRIGGERED")))
                .where(CustomerAftercareCase.case_type.in_(REDELIVERY_CASE_TYPES))
                .where(CustomerAftercareCase.delivery_note_printed_at.is_(None))
                .order_by(CustomerAftercareCase.created_at)
            ).all()
            sevdesk = str(sevdesk_contact_id or "").strip()
            wix = str(wix_contact_id or "").strip()
            email = str(customer_email or "").strip().casefold()
            matched = [
                row
                for row in candidates
                if self._customer_matches(
                    row, sevdesk_contact_id=sevdesk, wix_contact_id=wix, customer_email=email
                )
            ]
            target_date = self._date_only(invoice_date)
            if target_date is not None:
                matched = [
                    row
                    for row in matched
                    if row.created_at is None or row.created_at.date() <= target_date
                ]
            matched = [
                row
                for row in matched
                if not (row.dispatch_status in {"ATTACHED", "PRINTING"} and row.trigger_invoice_id)
            ]
            for row in matched:
                row.status = "TRIGGERED"
                row.trigger_reason = row.trigger_reason or "NEW_ORDER"
                row.triggered_at = func.now()
                row.trigger_invoice_id = str(invoice_id or "").strip()
                row.trigger_invoice_number = str(invoice_number or "").strip()
                row.trigger_wix_order_id = str(wix_order_id or "").strip()
                row.trigger_wix_order_number = str(wix_order_number or "").strip()
                row.dispatch_status = "PRINTING"
                row.snooze_mode = ""
                row.snoozed_until = None
                row.snooze_reason = ""
            session.flush()
            return list(matched)

    def mark_claim_printing(self, case_ids: Sequence[uuid.UUID]) -> None:
        with self._scope() as session:
            for case_id in case_ids:
                row = session.get(CustomerAftercareCase, case_id)
                if row is not None and row.dispatch_status == "ATTACHED":
                    row.dispatch_status = "PRINTING"
            session.flush()

    def release_invoice_claim(self, case_ids: Sequence[uuid.UUID]) -> None:
        """Make a failed physical print retryable without reopening a done case."""
        with self._scope() as session:
            for case_id in case_ids:
                row = session.get(CustomerAftercareCase, case_id)
                if row is not None and row.delivery_note_printed_at is None:
                    row.dispatch_status = "RETRYABLE"
            session.flush()

    def release_invoice_claim_for_invoice(self, invoice_id: str) -> list[CustomerAftercareCase]:
        target = str(invoice_id or "").strip()
        if not target:
            return []
        with self._scope() as session:
            rows = session.scalars(
                select(CustomerAftercareCase)
                .where(CustomerAftercareCase.trigger_invoice_id == target)
                .where(CustomerAftercareCase.dispatch_status == "PRINTING")
                .where(CustomerAftercareCase.delivery_note_printed_at.is_(None))
            ).all()
            for row in rows:
                row.dispatch_status = "RETRYABLE"
            session.flush()
            return list(rows)

    def snooze_case(
        self,
        case_id: uuid.UUID,
        *,
        mode: str,
        until: datetime.datetime | None = None,
        reason: str = "",
    ) -> CustomerAftercareCase | None:
        normalized = str(mode or "").strip().upper()
        if normalized not in {"NEXT_START", "UNTIL_DATE", "NEXT_ORDER"}:
            raise ValueError("Unbekannter Snooze-Modus")
        if normalized == "UNTIL_DATE" and until is None:
            raise ValueError("Snooze-Datum fehlt")
        with self._scope() as session:
            row = session.get(CustomerAftercareCase, case_id)
            if row is None or row.status not in {"WAITING", "TRIGGERED", "SNOOZED"}:
                return None
            row.snooze_mode = normalized
            row.snoozed_until = until if normalized == "UNTIL_DATE" else None
            row.snooze_reason = str(reason or "").strip()
            row.snoozed_at = func.now()
            row.status = "WAITING" if normalized == "NEXT_ORDER" else "SNOOZED"
            if normalized == "NEXT_ORDER":
                row.due_at = None
            row.dispatch_status = "SNOOZED" if row.dispatch_id else row.dispatch_status
            session.flush()
            return row

    def trigger_immediate(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        with self._scope() as session:
            row = session.get(CustomerAftercareCase, case_id)
            if row is None or row.status in {"RESOLVED", "CANCELLED", "IGNORED"}:
                return None
            row.status = "TRIGGERED"
            row.wait_for_next_order = False
            row.shipping_mode = "IMMEDIATE"
            row.due_at = None
            row.triggered_at = func.now()
            row.trigger_reason = "IMMEDIATE"
            row.snooze_mode = ""
            row.snoozed_until = None
            row.snooze_reason = ""
            if row.dispatch_id:
                row.dispatch_status = "ASAP"
            session.flush()
            return row

    def release_snoozes(
        self,
        *,
        mode: str | None = None,
        now: datetime.datetime | None = None,
    ) -> list[CustomerAftercareCase]:
        now = now or datetime.datetime.now(datetime.timezone.utc)
        with self._scope() as session:
            query = select(CustomerAftercareCase).where(CustomerAftercareCase.status == "SNOOZED")
            if mode:
                query = query.where(CustomerAftercareCase.snooze_mode == mode)
            else:
                query = query.where(CustomerAftercareCase.snooze_mode == "UNTIL_DATE").where(
                    CustomerAftercareCase.snoozed_until <= now
                )
            rows = list(session.scalars(query).all())
            for row in rows:
                row.status = "TRIGGERED"
                row.trigger_reason = "SNOOZE_EXPIRED"
                row.snooze_mode = ""
                row.snoozed_until = None
                row.dispatch_status = "ASAP" if row.dispatch_id else row.dispatch_status
            session.flush()
            return rows

    @staticmethod
    def _customer_matches(
        row: CustomerAftercareCase,
        *,
        sevdesk_contact_id: str,
        wix_contact_id: str,
        customer_email: str,
    ) -> bool:
        row_sevdesk = str(row.sevdesk_contact_id or "").strip()
        if sevdesk_contact_id and row_sevdesk:
            return row_sevdesk == sevdesk_contact_id
        row_wix = str(row.wix_contact_id or "").strip()
        if wix_contact_id and row_wix:
            return row_wix == wix_contact_id
        row_email = str(row.customer_email or "").strip().casefold()
        return bool(customer_email and row_email and row_email == customer_email)

    @staticmethod
    def _date_only(value: str) -> datetime.date | None:
        text_value = str(value or "").strip()
        if not text_value:
            return None
        try:
            return datetime.datetime.fromisoformat(text_value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.date.fromisoformat(text_value[:10])
            except ValueError:
                return None

    def mark_delivery_note_printed(self, case_ids: Sequence[uuid.UUID], *, path: str = "") -> None:
        with self._scope() as session:
            now = func.now()
            for case_id in case_ids:
                row = session.get(CustomerAftercareCase, case_id)
                if row is None:
                    continue
                row.delivery_note_printed_at = now
                row.delivery_note_path = str(path or "").strip()
                row.dispatch_status = "PRINTED"
                row.status = "RESOLVED"
                row.resolved_at = now
            session.flush()

    def set_dispatch(
        self,
        case_id: uuid.UUID,
        *,
        dispatch_id: str,
        dispatch_status: str,
    ) -> CustomerAftercareCase | None:
        with self._scope() as session:
            row = session.get(CustomerAftercareCase, case_id)
            if row is None:
                return None
            row.dispatch_id = str(dispatch_id or "").strip()
            row.dispatch_status = str(dispatch_status or "").strip()
            session.flush()
            return row

    def mark_dispatch_completed(self, dispatch_id: str) -> CustomerAftercareCase | None:
        """Close a redelivery when its generated OFFENE-SENDUNGEN case is completed."""
        dispatch = str(dispatch_id or "").strip()
        if not dispatch:
            return None
        with self._scope() as session:
            row = session.scalar(
                select(CustomerAftercareCase).where(CustomerAftercareCase.dispatch_id == dispatch)
            )
            if row is None:
                return None
            row.dispatch_status = "DONE"
            row.status = "RESOLVED"
            row.resolved_at = func.now()
            session.flush()
            return row

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

    def get_case_by_dispatch_id(self, dispatch_id: str) -> CustomerAftercareCase | None:
        with self._scope() as session:
            return session.scalar(
                select(CustomerAftercareCase).where(
                    CustomerAftercareCase.dispatch_id == str(dispatch_id or "").strip()
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
        shipping_mode: str | None = None,
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
            if shipping_mode is not None:
                row.shipping_mode = str(shipping_mode or "").strip()
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
            row.snooze_mode = ""
            row.snoozed_until = None
            row.snooze_reason = ""
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
