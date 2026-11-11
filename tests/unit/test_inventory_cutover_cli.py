from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from scripts.product_hub.check_inventory_cutover import (
    _resolve_database_url,
    assess_cutover,
    assess_runtime_configuration,
)
from xw_office.models.base import Base


def test_assess_cutover_is_read_only_and_fails_closed(tmp_path: Path, monkeypatch) -> None:
    for key in ("SEVDESK_API_TOKEN", "MS_GRAPH_TENANT_ID", "MS_GRAPH_CLIENT_ID", "MS_GRAPH_MAILBOX"):
        monkeypatch.delenv(key, raising=False)
    database_path = tmp_path / "cutover.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, class_=Session, future=True)() as session:
        before = {table.name: session.query(table).count() for table in Base.metadata.sorted_tables}

    payload = assess_cutover(database_url, shadow_enabled=False, master_enabled=False)

    assert payload["eligible"] is False
    assert payload["master_enabled"] is False
    assert any(check["code"] == "shadow_mode" and check["state"] == "blocked" for check in payload["checks"])
    config_check = next(check for check in payload["checks"] if check["code"] == "provider_credentials")
    assert config_check["state"] == "blocked"
    assert "SEVDESK_API_TOKEN" in config_check["detail"]
    assert any(check["code"] == "inventory_worker_service" and check["state"] == "manual" for check in payload["checks"])
    with sessionmaker(bind=engine, class_=Session, future=True)() as session:
        after = {table.name: session.query(table).count() for table in Base.metadata.sorted_tables}
    assert after == before


def test_cutover_cli_accepts_explicit_worker_activation_marker(monkeypatch) -> None:
    monkeypatch.setenv("XW_INVENTORY_WORKER_ACTIVE", "true")

    from scripts.product_hub.check_inventory_cutover import _runtime_configuration_checks

    worker_check = next(
        check for check in _runtime_configuration_checks() if check["code"] == "inventory_worker_service"
    )

    assert worker_check["state"] == "ready"
    assert "als aktiv konfiguriert" in worker_check["detail"]


def test_assess_cutover_can_skip_runtime_checks_for_database_service(tmp_path: Path) -> None:
    database_path = tmp_path / "database-only.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)

    payload = assess_cutover(database_url, include_runtime_configuration=False)

    assert not any(check["code"] == "provider_credentials" for check in payload["checks"])
    assert not any(check["code"] == "inventory_worker_service" for check in payload["checks"])


def test_assess_runtime_configuration_needs_no_database(monkeypatch) -> None:
    for key in ("SEVDESK_API_TOKEN", "MS_GRAPH_TENANT_ID", "MS_GRAPH_CLIENT_ID", "MS_GRAPH_MAILBOX"):
        monkeypatch.setenv(key, "configured")
    monkeypatch.setenv("XW_INVENTORY_WORKER_ACTIVE", "true")

    payload = assess_runtime_configuration()

    assert payload["eligible"] is True
    assert {check["state"] for check in payload["checks"]} == {"ready"}


def test_cutover_cli_resolves_public_database_url_without_argument(monkeypatch) -> None:
    monkeypatch.delenv("XW_INVENTORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_PUBLIC_URL", "postgresql://public.example/inventory")

    assert _resolve_database_url() == "postgresql://public.example/inventory"
    assert _resolve_database_url("postgresql://explicit.example/inventory") == (
        "postgresql://explicit.example/inventory"
    )
