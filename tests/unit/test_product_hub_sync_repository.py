"""Tests for the transactional outbox + sync repository (PR10)."""
from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub_sync import OutboxEvent
from xw_office.repositories.product_hub_sync import SyncRepository, append_outbox_event


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def repo(session_factory: sessionmaker[Session]) -> SyncRepository:
    return SyncRepository(session_factory)


def test_append_outbox_event_commits_with_callers_session(
    session_factory: sessionmaker[Session],
) -> None:
    aggregate_id = uuid.uuid4()
    with session_factory() as session:
        append_outbox_event(
            session,
            aggregate_type="product",
            aggregate_id=aggregate_id,
            event_type="product.updated",
            payload={"name": "New Name"},
        )
        session.commit()

    with session_factory() as session:
        events = session.query(OutboxEvent).all()
        assert len(events) == 1
        assert events[0].aggregate_id == aggregate_id
        assert events[0].event_type == "product.updated"
        assert events[0].processed_at is None
        assert events[0].attempts == 0


def test_claim_outbox_events_marks_claimed_and_respects_available_at(
    repo: SyncRepository, session_factory: sessionmaker[Session]
) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    with session_factory() as session:
        append_outbox_event(
            session, aggregate_type="product", aggregate_id=uuid.uuid4(),
            event_type="product.updated", payload={},
        )
        session.commit()

    claimed = repo.claim_outbox_events(limit=10, now=now)
    assert len(claimed) == 1
    assert claimed[0].claimed_at == now

    # already claimed -> not claimed again
    assert repo.claim_outbox_events(limit=10, now=now) == []


def test_claim_outbox_events_skips_future_available_at(
    repo: SyncRepository, session_factory: sessionmaker[Session]
) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    future = now + datetime.timedelta(hours=1)
    with session_factory() as session:
        event = append_outbox_event(
            session, aggregate_type="product", aggregate_id=uuid.uuid4(),
            event_type="product.updated", payload={},
        )
        event.available_at = future
        session.commit()

    assert repo.claim_outbox_events(limit=10, now=now) == []
    assert len(repo.claim_outbox_events(limit=10, now=future)) == 1


def test_mark_outbox_event_processed(
    repo: SyncRepository, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        event = append_outbox_event(
            session, aggregate_type="product", aggregate_id=uuid.uuid4(),
            event_type="product.updated", payload={},
        )
        session.commit()
        event_id = event.id

    updated = repo.mark_outbox_event_processed(event_id)
    assert updated.processed_at is not None


def test_mark_outbox_event_failed_bumps_attempts_and_reschedules(
    repo: SyncRepository, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        event = append_outbox_event(
            session, aggregate_type="product", aggregate_id=uuid.uuid4(),
            event_type="product.updated", payload={},
        )
        session.commit()
        event_id = event.id

    next_attempt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
    updated = repo.mark_outbox_event_failed(event_id, error="boom", next_available_at=next_attempt)

    assert updated.attempts == 1
    assert updated.last_error == "boom"
    assert updated.available_at == next_attempt
    assert updated.claimed_at is None


def test_list_dead_events(repo: SyncRepository, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        event = append_outbox_event(
            session, aggregate_type="product", aggregate_id=uuid.uuid4(),
            event_type="product.updated", payload={},
        )
        session.commit()
        event_id = event.id

    for _ in range(3):
        repo.mark_outbox_event_failed(
            event_id, error="boom", next_available_at=datetime.datetime.now(datetime.timezone.utc)
        )

    dead = repo.list_dead_events(max_attempts=3)
    assert len(dead) == 1
    assert dead[0].id == event_id
    assert repo.list_dead_events(max_attempts=10) == []


def test_sync_job_lifecycle(repo: SyncRepository) -> None:
    job = repo.create_sync_job(
        channel="wix", direction="push", job_type="product_push", correlation_id=uuid.uuid4()
    )
    assert job.status == "running"

    finished = repo.finish_sync_job(job.id, status="success")
    assert finished.status == "success"
    assert finished.finished_at is not None


def test_sync_conflict_lifecycle(repo: SyncRepository) -> None:
    entity_id = uuid.uuid4()
    conflict = repo.create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=entity_id,
        field_name="price",
        hub_value="19.99",
        external_value="24.99",
    )
    assert [c.id for c in repo.list_open_sync_conflicts(channel="wix")] == [conflict.id]

    resolved = repo.resolve_sync_conflict(conflict.id, resolution="keep_hub_and_push")
    assert resolved.resolved_at is not None
    assert repo.list_open_sync_conflicts(channel="wix") == []


def test_sync_cursor_upsert(repo: SyncRepository) -> None:
    created = repo.upsert_sync_cursor(channel="wix", stream="products", cursor_value="page-1")
    assert created.cursor_value == "page-1"

    updated = repo.upsert_sync_cursor(channel="wix", stream="products", cursor_value="page-2")
    assert updated.id == created.id
    assert updated.cursor_value == "page-2"

    fetched = repo.get_sync_cursor(channel="wix", stream="products")
    assert fetched is not None
    assert fetched.cursor_value == "page-2"
