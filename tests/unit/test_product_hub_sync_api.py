"""Tests for the sync/conflict/outbox-worker HTTP API (PR11)."""
from __future__ import annotations

from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.web import ContentWebSettings, create_app


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    db_file = tmp_path / "product_hub_sync.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    return f"sqlite:///{db_file}"


def _client(db_path: str, *, token: str = "secret-token", edit_enabled: bool = True) -> TestClient:
    settings = ContentWebSettings(
        bootstrap_token=token,
        database_url=db_path,
        product_hub_catalog_read_enabled=True,
        product_hub_edit_enabled=edit_enabled,
    )
    return TestClient(create_app(settings))


def _auth_headers(token: str = "secret-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_conflict(db_path: str) -> uuid.UUID:
    engine = create_engine(db_path, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    repo = SyncRepository(factory)
    conflict = repo.create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=uuid.uuid4(),
        field_name="name",
        hub_value="Hub Name",
        external_value="Wix Name",
    )
    engine.dispose()
    return conflict.id


def test_sync_endpoints_fail_closed_when_edit_disabled(db_path: str) -> None:
    client = _client(db_path, edit_enabled=False)
    response = client.get("/api/v1/sync/conflicts", headers=_auth_headers())
    assert response.status_code == 503


def test_list_conflicts(db_path: str) -> None:
    conflict_id = _seed_conflict(db_path)
    client = _client(db_path)

    response = client.get("/api/v1/sync/conflicts", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(conflict_id)
    assert body[0]["field_name"] == "name"


def test_list_conflicts_filters_by_channel(db_path: str) -> None:
    _seed_conflict(db_path)
    client = _client(db_path)

    response = client.get("/api/v1/sync/conflicts?channel=sevdesk", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == []


def test_resolve_conflict_ignore_once(db_path: str) -> None:
    conflict_id = _seed_conflict(db_path)
    client = _client(db_path)

    response = client.post(
        f"/api/v1/sync/conflicts/{conflict_id}/resolve",
        headers=_auth_headers(),
        json={"resolution": "ignore_once"},
    )

    assert response.status_code == 200
    assert response.json()["resolution"] == "ignore_once"
    assert response.json()["resolved_at"] is not None

    remaining = client.get("/api/v1/sync/conflicts", headers=_auth_headers()).json()
    assert remaining == []


def test_resolve_conflict_unknown_id_returns_404(db_path: str) -> None:
    client = _client(db_path)
    response = client.post(
        f"/api/v1/sync/conflicts/{uuid.uuid4()}/resolve",
        headers=_auth_headers(),
        json={"resolution": "ignore_once"},
    )
    assert response.status_code == 404


def test_resolve_conflict_invalid_resolution_returns_400(db_path: str) -> None:
    conflict_id = _seed_conflict(db_path)
    client = _client(db_path)

    response = client.post(
        f"/api/v1/sync/conflicts/{conflict_id}/resolve",
        headers=_auth_headers(),
        json={"resolution": "not_a_real_resolution"},
    )
    assert response.status_code == 400


def test_run_worker_once_returns_summary_with_no_events(db_path: str) -> None:
    client = _client(db_path)
    response = client.post("/api/v1/sync/worker/run-once", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body == {"processed": 0, "failed": 0, "skipped_no_handler": 0, "errors": []}


def test_dead_events_endpoint_empty_by_default(db_path: str) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/sync/worker/dead-events", headers=_auth_headers())
    assert response.status_code == 200
    assert response.json() == []
