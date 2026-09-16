"""Tests for the outbox retry worker (PR10)."""
from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub_sync import OutboxEvent
from xw_office.repositories.product_hub_sync import SyncRepository, append_outbox_event
from xw_office.services.product_hub.outbox_worker import OutboxWorker


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _write_event(session_factory: sessionmaker[Session], *, event_type: str = "product.updated") -> uuid.UUID:
    with session_factory() as session:
        event = append_outbox_event(
            session,
            aggregate_type="product",
            aggregate_id=uuid.uuid4(),
            event_type=event_type,
            payload={"x": "1"},
        )
        session.commit()
        return event.id


def test_process_once_calls_registered_handler_and_marks_processed(
    session_factory: sessionmaker[Session],
) -> None:
    event_id = _write_event(session_factory)
    worker = OutboxWorker(session_factory)
    seen: list[uuid.UUID] = []
    worker.register_handler("product.updated", lambda event: seen.append(event.id))

    summary = worker.process_once()

    assert summary.processed == 1
    assert summary.failed == 0
    assert seen == [event_id]

    repo = SyncRepository(session_factory)
    assert repo.get_outbox_event(event_id).processed_at is not None  # type: ignore[union-attr]


def test_process_once_without_handler_releases_without_penalty(
    session_factory: sessionmaker[Session],
) -> None:
    event_id = _write_event(session_factory, event_type="nobody.listens")
    worker = OutboxWorker(session_factory)

    summary = worker.process_once()

    assert summary.skipped_no_handler == 1
    repo = SyncRepository(session_factory)
    event = repo.get_outbox_event(event_id)
    assert event is not None
    assert event.claimed_at is None
    assert event.attempts == 0
    assert event.processed_at is None


def test_process_once_handler_failure_schedules_backoff_retry(
    session_factory: sessionmaker[Session],
) -> None:
    event_id = _write_event(session_factory)
    worker = OutboxWorker(
        session_factory, base_delay=datetime.timedelta(seconds=10), max_delay=datetime.timedelta(minutes=10)
    )

    def failing_handler(event: OutboxEvent) -> None:
        raise RuntimeError("channel unreachable")

    worker.register_handler("product.updated", failing_handler)
    summary = worker.process_once()

    assert summary.failed == 1
    assert "channel unreachable" in summary.errors[0]

    repo = SyncRepository(session_factory)
    event = repo.get_outbox_event(event_id)
    assert event is not None
    assert event.attempts == 1
    assert event.last_error == "channel unreachable"
    assert event.claimed_at is None
    # SQLite drops tzinfo on round-trip (unlike Postgres) - compare naive-to-naive.
    now_naive = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    assert event.available_at > now_naive


def test_backoff_delay_grows_and_caps(session_factory: sessionmaker[Session]) -> None:
    worker = OutboxWorker(
        session_factory,
        base_delay=datetime.timedelta(seconds=60),
        max_delay=datetime.timedelta(seconds=300),
    )
    assert worker._backoff_delay(0) == datetime.timedelta(seconds=60)
    assert worker._backoff_delay(1) == datetime.timedelta(seconds=120)
    assert worker._backoff_delay(2) == datetime.timedelta(seconds=240)
    assert worker._backoff_delay(10) == datetime.timedelta(seconds=300)  # capped


def test_list_dead_events_after_exhausting_attempts(session_factory: sessionmaker[Session]) -> None:
    event_id = _write_event(session_factory)
    worker = OutboxWorker(
        session_factory,
        base_delay=datetime.timedelta(seconds=0),
        max_attempts=2,
    )

    def failing_handler(event: OutboxEvent) -> None:
        raise RuntimeError("still broken")

    worker.register_handler("product.updated", failing_handler)
    worker.process_once()
    worker.process_once()

    dead = worker.list_dead_events()
    assert [e.id for e in dead] == [event_id]
