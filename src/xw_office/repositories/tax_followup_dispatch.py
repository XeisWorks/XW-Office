"""Persistence boundary for idempotent tax follow-up delivery."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.tax_followup_dispatch import TaxFollowupDispatch


class TaxFollowupDispatchRepository:
    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    def get_or_create(
        self, *, filing_kind: str, period: str, calculation_hash: str, recipient_kind: str,
        attachment_sha256: str | None = None,
    ) -> TaxFollowupDispatch:
        with self._scope() as session:
            row = session.execute(select(TaxFollowupDispatch).where(
                TaxFollowupDispatch.filing_kind == filing_kind,
                TaxFollowupDispatch.period == period,
                TaxFollowupDispatch.calculation_hash == calculation_hash,
                TaxFollowupDispatch.recipient_kind == recipient_kind,
            )).scalar_one_or_none()
            if row is not None:
                return row
            row = TaxFollowupDispatch(
                dispatch_key=f"tax:{filing_kind}:{period}:{calculation_hash}:{recipient_kind}",
                filing_kind=filing_kind,
                period=period,
                calculation_hash=calculation_hash,
                recipient_kind=recipient_kind,
                message_correlation_id=uuid.uuid4().hex,
                attachment_sha256=attachment_sha256,
            )
            session.add(row)
            session.flush()
            return row

    def mark_sent(self, row: TaxFollowupDispatch) -> None:
        with self._scope() as session:
            current = session.get(TaxFollowupDispatch, row.id)
            if current is not None:
                current.status = "sent"
                current.attempt_count += 1
                current.sent_at = datetime.now(UTC)
                current.last_error_code = None
                current.last_error_detail = None

    def mark_failed(self, row: TaxFollowupDispatch, *, code: str, detail: str = "") -> None:
        with self._scope() as session:
            current = session.get(TaxFollowupDispatch, row.id)
            if current is not None:
                current.status = "failed"
                current.attempt_count += 1
                current.last_error_code = code[:80]
                current.last_error_detail = detail[:1000] or None

    def mark_uncertain(self, row: TaxFollowupDispatch, *, detail: str = "") -> None:
        with self._scope() as session:
            current = session.get(TaxFollowupDispatch, row.id)
            if current is not None:
                current.status = "pending"
                current.attempt_count += 1
                current.last_error_code = "graph_timeout_unknown"
                current.last_error_detail = detail[:1000] or None

    def _scope(self):
        if isinstance(self._session_or_factory, Session):
            from contextlib import nullcontext
            return nullcontext(self._session_or_factory)
        return session_scope(self._session_or_factory)
