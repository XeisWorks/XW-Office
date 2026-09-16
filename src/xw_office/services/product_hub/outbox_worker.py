"""Transactional outbox retry worker (PR10).

Claims available ``outbox_event`` rows, dispatches each to a registered handler by
``event_type``, and applies bounded exponential backoff on failure. There is no
handler registered anywhere in the codebase yet — PR11's Wix push adapter is the
first real consumer — so today, calling :meth:`OutboxWorker.process_once` on real
production events just leaves them claimed-then-released, waiting. This is exercised
end-to-end in tests via a fake handler.

Deployment shape per docs/product_hub/XW_PRODUCT_HUB_IMPLEMENTATION.yaml
(``worker.pattern: postgres_outbox``, ``deployment: separate_Railway_worker_or_
periodic_worker``): this class is deliberately transport-agnostic — call
``process_once()`` from a scheduled job, a small standalone loop, or a management
command. Wiring an actual Railway cron/worker service is not part of this PR.
"""
from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.product_hub_sync import OutboxEvent
from xw_office.repositories.product_hub_sync import SyncRepository

#: A handler receives the claimed event and either returns normally (success) or
#: raises (failure — triggers backoff). It owns its own side effects (e.g. calling
#: Wix) and must be idempotent, since redelivery after a crash is possible.
OutboxHandler = Callable[[OutboxEvent], None]

DEFAULT_BASE_DELAY = datetime.timedelta(seconds=60)
DEFAULT_MAX_DELAY = datetime.timedelta(hours=1)
DEFAULT_MAX_ATTEMPTS = 8


@dataclass
class OutboxRunSummary:
    """Outcome of one :meth:`OutboxWorker.process_once` call."""

    processed: int = 0
    failed: int = 0
    skipped_no_handler: int = 0
    errors: list[str] = field(default_factory=list)


class OutboxWorker:
    """Claims + dispatches outbox events; owns retry/backoff, not delivery."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        base_delay: datetime.timedelta = DEFAULT_BASE_DELAY,
        max_delay: datetime.timedelta = DEFAULT_MAX_DELAY,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._repo = SyncRepository(session_factory)
        self._handlers: dict[str, OutboxHandler] = {}
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._max_attempts = max_attempts

    def register_handler(self, event_type: str, handler: OutboxHandler) -> None:
        self._handlers[event_type] = handler

    def _backoff_delay(self, attempts: int) -> datetime.timedelta:
        delay: datetime.timedelta = self._base_delay * (2**attempts)
        return delay if delay < self._max_delay else self._max_delay

    def process_once(self, *, limit: int = 50) -> OutboxRunSummary:
        summary = OutboxRunSummary()
        now = datetime.datetime.now(datetime.timezone.utc)
        for event in self._repo.claim_outbox_events(limit=limit, now=now):
            handler = self._handlers.get(event.event_type)
            if handler is None:
                # No consumer registered yet for this event type (expected until
                # PR11+ registers real channel handlers) — release without penalty
                # rather than spending a retry attempt on something nobody claims yet.
                self._repo.release_outbox_event(event.id)
                summary.skipped_no_handler += 1
                continue
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 - any handler failure triggers backoff
                next_attempt_at = now + self._backoff_delay(event.attempts)
                self._repo.mark_outbox_event_failed(
                    event.id, error=str(exc), next_available_at=next_attempt_at
                )
                summary.failed += 1
                summary.errors.append(f"{event.event_type}:{event.id}: {exc}")
            else:
                self._repo.mark_outbox_event_processed(event.id)
                summary.processed += 1
        return summary

    def list_dead_events(self) -> list[OutboxEvent]:
        return self._repo.list_dead_events(max_attempts=self._max_attempts)
