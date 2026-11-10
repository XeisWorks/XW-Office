"""Shared test fixtures for XeisWorks Office."""
from __future__ import annotations

import socket

import pytest

from xw_office.core.config import AppConfig
from xw_office.core.container import Container


@pytest.fixture(autouse=True)
def isolate_tests_from_credentials_and_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
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

    original_connect = socket.socket.connect

    def connect_local_only(sock: socket.socket, address: object) -> None:
        if isinstance(address, tuple) and address:
            host = str(address[0]).strip().casefold()
            if host not in {"localhost", "127.0.0.1", "::1"}:
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
