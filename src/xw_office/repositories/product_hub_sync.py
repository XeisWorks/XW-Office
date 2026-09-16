"""Repository layer for the XW Product Hub transactional outbox + sync schema (PR10).

``append_outbox_event`` is deliberately a plain function, not a method on a
scope-owning repository class: it must run inside the *caller's* existing
transaction (the business write it describes), never open its own. Everything else
here (:class:`SyncRepository`) is a normal scope-owning repository for the worker
side and for PR11's future sync_job/sync_conflict/sync_cursor bookkeeping.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime
import uuid
from collections.abc import Generator, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub_sync import (
    ExternalPayloadArchive,
    OutboxEvent,
    SyncConflict,
    SyncCursor,
    SyncJob,
)


def append_outbox_event(
    session: Session,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: Mapping[str, object],
) -> OutboxEvent:
    """Write one outbox row on the caller's session — commits with their transaction."""
    event = OutboxEvent(
        id=uuid.uuid4(),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    session.flush()
    return event


class SyncRepository:
    """Data access for outbox claim/retry and the sync_job/conflict/cursor tables."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    # -- outbox ---------------------------------------------------------------------

    def get_outbox_event(self, event_id: uuid.UUID) -> OutboxEvent | None:
        with self._scope() as session:
            return session.get(OutboxEvent, event_id)

    def claim_outbox_events(
        self, *, limit: int = 50, now: datetime.datetime | None = None
    ) -> list[OutboxEvent]:
        """Mark up to ``limit`` available, unprocessed events as claimed and return them.

        Single-consumer assumption (one worker instance, per the build plan's "separate
        Railway worker or periodic worker" — not a replica-scaled pool), so this uses a
        plain select+update rather than ``FOR UPDATE SKIP LOCKED``, which also keeps the
        SQLite test suite working (Postgres-only locking clauses aren't portable, same
        reasoning as the "one default variant" note in models/product_hub.py).
        """
        moment = now or datetime.datetime.now(datetime.timezone.utc)
        with self._scope() as session:
            stmt = (
                select(OutboxEvent)
                .where(
                    OutboxEvent.processed_at.is_(None),
                    OutboxEvent.claimed_at.is_(None),
                    OutboxEvent.available_at <= moment,
                )
                .order_by(OutboxEvent.available_at)
                .limit(limit)
            )
            events = list(session.scalars(stmt).all())
            for event in events:
                event.claimed_at = moment
            session.flush()
            return events

    def mark_outbox_event_processed(self, event_id: uuid.UUID) -> OutboxEvent:
        with self._scope() as session:
            event = session.get(OutboxEvent, event_id)
            if event is None:
                raise KeyError(f"Outbox event {event_id} not found")
            event.processed_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return event

    def mark_outbox_event_failed(
        self, event_id: uuid.UUID, *, error: str, next_available_at: datetime.datetime
    ) -> OutboxEvent:
        with self._scope() as session:
            event = session.get(OutboxEvent, event_id)
            if event is None:
                raise KeyError(f"Outbox event {event_id} not found")
            event.attempts += 1
            event.last_error = error[:4000]
            event.available_at = next_available_at
            event.claimed_at = None
            session.flush()
            return event

    def release_outbox_event(self, event_id: uuid.UUID) -> None:
        """Un-claim without penalty — used when no handler is registered yet, so the
        event waits for a future worker run instead of burning a retry attempt."""
        with self._scope() as session:
            event = session.get(OutboxEvent, event_id)
            if event is None:
                raise KeyError(f"Outbox event {event_id} not found")
            event.claimed_at = None
            session.flush()

    def list_dead_events(self, *, max_attempts: int) -> list[OutboxEvent]:
        """Events that exhausted retries and still aren't processed — the build plan's
        "dead/error state sichtbar" requirement, exposed as a query rather than a
        stored status column (matches the schema spec exactly)."""
        with self._scope() as session:
            stmt = select(OutboxEvent).where(
                OutboxEvent.processed_at.is_(None),
                OutboxEvent.attempts >= max_attempts,
            )
            return list(session.scalars(stmt).all())

    # -- sync jobs --------------------------------------------------------------------

    def create_sync_job(
        self,
        *,
        channel: str,
        direction: str,
        job_type: str,
        correlation_id: uuid.UUID,
        requested_by: str = "",
    ) -> SyncJob:
        with self._scope() as session:
            job = SyncJob(
                id=uuid.uuid4(),
                channel=channel,
                direction=direction,
                job_type=job_type,
                status="running",
                correlation_id=correlation_id,
                started_at=datetime.datetime.now(datetime.timezone.utc),
                requested_by=requested_by or None,
            )
            session.add(job)
            session.flush()
            return job

    def finish_sync_job(
        self, job_id: uuid.UUID, *, status: str, error_summary: str = ""
    ) -> SyncJob:
        with self._scope() as session:
            job = session.get(SyncJob, job_id)
            if job is None:
                raise KeyError(f"Sync job {job_id} not found")
            job.status = status
            job.finished_at = datetime.datetime.now(datetime.timezone.utc)
            job.error_summary = error_summary or None
            session.flush()
            return job

    # -- conflicts / cursors -----------------------------------------------------------

    def create_sync_conflict(
        self,
        *,
        channel: str,
        entity_type: str,
        internal_entity_id: uuid.UUID,
        field_name: str,
        hub_value: object | None = None,
        external_value: object | None = None,
        external_updated_at: datetime.datetime | None = None,
    ) -> SyncConflict:
        with self._scope() as session:
            conflict = SyncConflict(
                id=uuid.uuid4(),
                channel=channel,
                entity_type=entity_type,
                internal_entity_id=internal_entity_id,
                field_name=field_name,
                hub_value=hub_value,
                external_value=external_value,
                detected_at=datetime.datetime.now(datetime.timezone.utc),
                external_updated_at=external_updated_at,
            )
            session.add(conflict)
            session.flush()
            return conflict

    def get_sync_conflict(self, conflict_id: uuid.UUID) -> SyncConflict | None:
        with self._scope() as session:
            return session.get(SyncConflict, conflict_id)

    def get_open_conflict(
        self, *, channel: str, entity_type: str, internal_entity_id: uuid.UUID, field_name: str
    ) -> SyncConflict | None:
        with self._scope() as session:
            return session.scalar(
                select(SyncConflict).where(
                    SyncConflict.channel == channel,
                    SyncConflict.entity_type == entity_type,
                    SyncConflict.internal_entity_id == internal_entity_id,
                    SyncConflict.field_name == field_name,
                    SyncConflict.resolved_at.is_(None),
                )
            )

    def list_open_sync_conflicts(self, *, channel: str | None = None) -> list[SyncConflict]:
        with self._scope() as session:
            stmt = select(SyncConflict).where(SyncConflict.resolved_at.is_(None))
            if channel is not None:
                stmt = stmt.where(SyncConflict.channel == channel)
            return list(session.scalars(stmt).all())

    def resolve_sync_conflict(
        self, conflict_id: uuid.UUID, *, resolution: str, resolved_by: str = ""
    ) -> SyncConflict:
        with self._scope() as session:
            conflict = session.get(SyncConflict, conflict_id)
            if conflict is None:
                raise KeyError(f"Sync conflict {conflict_id} not found")
            conflict.resolution = resolution
            conflict.resolved_by = resolved_by or None
            conflict.resolved_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return conflict

    # -- external payload archive (drift-detection baseline, PR11) --------------------

    def archive_external_payload(
        self,
        *,
        channel: str,
        entity_type: str,
        external_id: str,
        payload: Mapping[str, object],
        payload_hash: str,
    ) -> ExternalPayloadArchive:
        with self._scope() as session:
            row = ExternalPayloadArchive(
                id=uuid.uuid4(),
                channel=channel,
                entity_type=entity_type,
                external_id=external_id,
                payload=payload,
                payload_hash=payload_hash,
                fetched_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(row)
            session.flush()
            return row

    def get_latest_external_payload(
        self, *, channel: str, entity_type: str, external_id: str
    ) -> ExternalPayloadArchive | None:
        with self._scope() as session:
            stmt = (
                select(ExternalPayloadArchive)
                .where(
                    ExternalPayloadArchive.channel == channel,
                    ExternalPayloadArchive.entity_type == entity_type,
                    ExternalPayloadArchive.external_id == external_id,
                )
                .order_by(ExternalPayloadArchive.fetched_at.desc())
            )
            return session.scalars(stmt).first()

    def get_sync_cursor(self, *, channel: str, stream: str) -> SyncCursor | None:
        with self._scope() as session:
            return session.scalar(
                select(SyncCursor).where(SyncCursor.channel == channel, SyncCursor.stream == stream)
            )

    def upsert_sync_cursor(
        self,
        *,
        channel: str,
        stream: str,
        cursor_value: str | None,
        last_seen_updated_at: datetime.datetime | None = None,
    ) -> SyncCursor:
        with self._scope() as session:
            cursor = session.scalar(
                select(SyncCursor).where(SyncCursor.channel == channel, SyncCursor.stream == stream)
            )
            if cursor is None:
                cursor = SyncCursor(id=uuid.uuid4(), channel=channel, stream=stream)
                session.add(cursor)
            cursor.cursor_value = cursor_value
            cursor.last_seen_updated_at = last_seen_updated_at
            cursor.updated_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return cursor
