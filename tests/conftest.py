"""Shared test fixtures for XeisWorks Office."""
from __future__ import annotations

import socket
import os
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from xw_office.core.config import AppConfig
from xw_office.core.container import Container


@pytest.fixture(autouse=True)
def isolate_tests_from_credentials_and_external_network(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Keep ordinary tests independent of workstation .env files and live services."""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "true")
    for name in (
        "DATABASE_URL",
        "SEVDESK_API_TOKEN",
        "WIX_API_KEY",
        "WIX_API_KEY_DATA",
        "WIX_SITE_ID",
        "WIX_ACCOUNT_ID",
        "MOLLIE_API_KEY",
        "STRIPE_SECRET_KEY",
        "OPENAI_API_KEY",
        "CLICKUP_API_TOKEN",
        "RAILWAY_TOKEN",
        "OUTLOOK_SENDER_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)

    allowed_hosts = {"localhost", "127.0.0.1", "::1"}
    test_postgres_url = str(os.environ.get("XW_TEST_POSTGRES_URL") or "").strip()
    allow_remote_postgres = str(
        os.environ.get("XW_TEST_POSTGRES_ALLOW_REMOTE") or ""
    ).strip() == "1"
    path = Path(str(request.node.path))
    is_postgres_integration_test = (
        path.parent.name == "integration" and path.name == "test_invoice_inventory_postgres.py"
    )
    if test_postgres_url:
        try:
            test_db_host = str(make_url(test_postgres_url).host or "").strip().casefold()
        except Exception:
            test_db_host = ""
        if test_db_host in {"localhost", "127.0.0.1", "::1"}:
            allowed_hosts.add(test_db_host)
        elif allow_remote_postgres and is_postgres_integration_test and test_db_host:
            allowed_hosts.add(test_db_host)
            try:
                allowed_hosts.update(
                    str(address[4][0]).casefold()
                    for address in socket.getaddrinfo(
                        test_db_host, None, type=socket.SOCK_STREAM
                    )
                )
            except OSError as exc:
                raise RuntimeError(
                    "Opt-in PostgreSQL-Testhost konnte nicht aufgeloest werden"
                ) from exc
        else:
            monkeypatch.delenv("XW_TEST_POSTGRES_URL", raising=False)
    if not (allow_remote_postgres and is_postgres_integration_test):
        monkeypatch.delenv("XW_TEST_POSTGRES_ALLOW_REMOTE", raising=False)

    original_connect = socket.socket.connect

    def connect_local_only(sock: socket.socket, address: object) -> None:
        if isinstance(address, tuple) and address:
            host = str(address[0]).strip().casefold()
            if host.casefold() not in allowed_hosts:
                raise RuntimeError(
                    f"External network access is disabled in the test process: {host}"
                )
        return original_connect(sock, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", connect_local_only)


@pytest.fixture
def app_config() -> AppConfig:
    """Minimal test configuration."""
    return AppConfig()


@pytest.fixture
def container(app_config: AppConfig) -> Container:
    """DI container with test config."""
    return Container(app_config)
