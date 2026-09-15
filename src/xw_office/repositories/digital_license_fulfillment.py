"""Database repository for digital license fulfillment workflows."""
from __future__ import annotations

from contextlib import contextmanager
import datetime
import json
from collections.abc import Generator, Iterable
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.digital_license_fulfillment import DigitalLicenseFulfillment


OPEN_STATES = (
    "DISCOVERED",
    "PENDING_DECISION",
    "DEFERRED",
    "PREPARING_FILES",
    "AWAITING_PDF_REVIEW",
    "DRAFT_READY",
    "COMPLETING",
    "ERROR",
)


class DigitalLicenseFulfillmentRepository:
    """Persist one workflow per invoice with PostgreSQL advisory locking."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    @staticmethod
    def _lock(session: Session, key: str) -> None:
        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})

    def get(self, invoice_id: str) -> DigitalLicenseFulfillment | None:
        with self._scope() as session:
            return session.get(DigitalLicenseFulfillment, str(invoice_id).strip())

    def list_open(self, *, limit: int = 100) -> list[DigitalLicenseFulfillment]:
        return self.list_by_states(OPEN_STATES, limit=limit)

    def list_by_states(
        self,
        states: Iterable[str] | None = None,
        *,
        limit: int = 100,
    ) -> list[DigitalLicenseFulfillment]:
        with self._scope() as session:
            query = select(DigitalLicenseFulfillment)
            normalized_states = tuple(str(state).strip() for state in (states or OPEN_STATES) if str(state).strip())
            if normalized_states:
                query = query.where(DigitalLicenseFulfillment.state.in_(normalized_states))
            query = query.order_by(DigitalLicenseFulfillment.updated_at.asc()).limit(max(1, min(int(limit), 1000)))
            return list(session.scalars(query))

    def upsert_candidate(
        self,
        *,
        invoice_id: str,
        invoice_number: str,
        order_reference: str,
        state: str = "PENDING_DECISION",
    ) -> DigitalLicenseFulfillment:
        invoice_key = str(invoice_id or "").strip()
        if not invoice_key:
            raise ValueError("invoice_id is required")
        with self._scope() as session:
            self._lock(session, f"digital-license:{invoice_key}")
            row = session.get(DigitalLicenseFulfillment, invoice_key)
            if row is None:
                row = DigitalLicenseFulfillment(
                    invoice_id=invoice_key,
                    invoice_number=str(invoice_number or "").strip(),
                    order_reference=str(order_reference or "").strip(),
                    state=str(state or "PENDING_DECISION").strip(),
                )
                session.add(row)
            else:
                row.invoice_number = str(invoice_number or row.invoice_number or "").strip()
                row.order_reference = str(order_reference or row.order_reference or "").strip()
                if row.state == "DISCOVERED":
                    row.state = str(state or "PENDING_DECISION").strip()
            session.flush()
            return row

    def transition(self, invoice_id: str, state: str, *, error: str = "", **fields: Any) -> DigitalLicenseFulfillment:
        with self._scope() as session:
            key = str(invoice_id or "").strip()
            self._lock(session, f"digital-license:{key}")
            row = session.get(DigitalLicenseFulfillment, key)
            if row is None:
                raise KeyError(f"Unknown digital license invoice: {key}")
            row.state = str(state or "ERROR").strip()
            row.last_error = str(error or "").strip()[:4000]
            for name, value in fields.items():
                if hasattr(row, name):
                    setattr(row, name, value)
            session.flush()
            return row

    def mark_completed(self, invoice_id: str, *, wix_fulfilled_at: datetime.datetime | None = None) -> DigitalLicenseFulfillment:
        now = datetime.datetime.now(datetime.timezone.utc)
        return self.transition(
            invoice_id,
            "COMPLETED",
            error="",
            completed_at=now,
            wix_fulfilled_at=wix_fulfilled_at or now,
        )

    def set_files(self, invoice_id: str, files: Iterable[dict[str, Any]], *, invoice_path: str = "") -> DigitalLicenseFulfillment:
        payload = json.dumps(list(files), ensure_ascii=False, sort_keys=True)
        return self.transition(
            invoice_id,
            "AWAITING_PDF_REVIEW",
            licensed_files_json=payload,
            invoice_attachment_path=str(invoice_path or "").strip(),
            last_error="",
        )
