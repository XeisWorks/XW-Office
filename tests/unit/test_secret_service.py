"""Tests for SecretService DB/encryption/env fallback behavior."""

from __future__ import annotations

import json

from cryptography.fernet import Fernet

from xw_studio.core.config import AppConfig, SevdeskSection, WixSection
from xw_studio.services.secrets.service import SecretService


class _RepoStub:
    def __init__(self) -> None:
        self._db: dict[str, bytes] = {}

    def get_ciphertext(self, name: str) -> bytes | None:
        return self._db.get(name)

    def get_all_ciphertexts(self) -> dict[str, bytes]:
        return dict(self._db)

    def upsert_ciphertext(self, name: str, ciphertext: bytes) -> object:
        self._db[name] = ciphertext
        return object()


def test_get_secret_prefers_db_over_config() -> None:
    key = Fernet.generate_key().decode("ascii")
    cfg = AppConfig(
        fernet_master_key=key,
        sevdesk=SevdeskSection(api_token="env-token"),
    )
    repo = _RepoStub()
    service = SecretService(cfg, repo)
    service.save_secret("SEVDESK_API_TOKEN", "db-token")
    assert service.get_secret("SEVDESK_API_TOKEN") == "db-token"


def test_get_secret_falls_back_to_config() -> None:
    cfg = AppConfig(
        sevdesk=SevdeskSection(api_token="env-token"),
        wix=WixSection(api_key="wix-key", site_id="site-1", account_id="acct-1"),
    )
    service = SecretService(cfg, None)
    assert service.get_secret("SEVDESK_API_TOKEN") == "env-token"
    assert service.get_secret("WIX_API_KEY") == "wix-key"


def test_get_secret_falls_back_to_environment(monkeypatch) -> None:
    monkeypatch.setenv("MOLLIE_ACCESS_TOKEN", "mollie-env")
    service = SecretService(AppConfig(), None)
    assert service.get_secret("MOLLIE_ACCESS_TOKEN") == "mollie-env"


def test_graph_keys_fall_back_to_legacy_config(monkeypatch, tmp_path) -> None:
    legacy_config = tmp_path / "config.json"
    legacy_config.write_text(
        json.dumps(
            {
                "graph": {
                    "tenant_id": "tenant-legacy",
                    "client_id": "client-legacy",
                    "mailbox_user": "shop@example.test",
                    "transfer_mailbox_user": "transfer@example.test",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XW_STUDIO_LEGACY_SEVDESK_CONFIG", str(legacy_config))
    monkeypatch.delenv("MS_GRAPH_TENANT_ID", raising=False)
    monkeypatch.delenv("MS_GRAPH_CLIENT_ID", raising=False)
    monkeypatch.delenv("MS_GRAPH_MAILBOX", raising=False)
    monkeypatch.delenv("MS_GRAPH_TRANSFER_MAILBOX", raising=False)

    service = SecretService(AppConfig(), None)

    assert service.get_secret("MS_GRAPH_TENANT_ID") == "tenant-legacy"
    assert service.get_secret("MS_GRAPH_CLIENT_ID") == "client-legacy"
    assert service.get_secret("MS_GRAPH_MAILBOX") == "shop@example.test"
    assert service.get_secret("MS_GRAPH_TRANSFER_MAILBOX") == "transfer@example.test"
