"""Idempotent orchestration for tax report and transfer mails."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from xw_office.repositories.tax_followup_dispatch import TaxFollowupDispatchRepository


@dataclass(frozen=True)
class DispatchOutcome:
    status: str
    dispatch_key: str
    attempt_count: int


class TaxFollowupService:
    def __init__(self, repository: TaxFollowupDispatchRepository) -> None:
        self._repository = repository

    def send_once(
        self, *, filing_kind: str, period: str, calculation_hash: str,
        recipient_kind: str, send: Callable[[], None], attachment: bytes | None = None,
    ) -> DispatchOutcome:
        digest = sha256(attachment).hexdigest() if attachment else None
        row = self._repository.get_or_create(
            filing_kind=filing_kind, period=period, calculation_hash=calculation_hash,
            recipient_kind=recipient_kind, attachment_sha256=digest,
        )
        if row.status == "sent":
            return DispatchOutcome("already_sent", row.dispatch_key, row.attempt_count)
        if row.status == "pending" and row.attempt_count > 0:
            raise RuntimeError("Versandstatus ist nach einem unklaren Vorgang pending; zuerst prüfen.")
        try:
            send()
        except Exception as exc:
            if "timeout" in type(exc).__name__.casefold():
                self._repository.mark_uncertain(row, detail=type(exc).__name__)
            else:
                self._repository.mark_failed(row, code="graph_send_failed", detail=type(exc).__name__)
            raise
        self._repository.mark_sent(row)
        return DispatchOutcome("sent", row.dispatch_key, row.attempt_count + 1)
