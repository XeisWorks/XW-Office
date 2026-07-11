"""Encrypted secret access (DB-first) with config fallback."""
from __future__ import annotations

from threading import RLock

import os
import json
from pathlib import Path

from xw_studio.core.config import AppConfig
from xw_studio.core.exceptions import ConfigError
from xw_studio.core.token_crypto import decrypt_secret, encrypt_secret
from xw_studio.repositories.api_secret import ApiSecretRepository

SUPPORTED_SECRET_KEYS: tuple[str, ...] = (
    "SEVDESK_API_TOKEN",
    "WIX_API_KEY",
    "WIX_SITE_ID",
    "WIX_ACCOUNT_ID",
    "MOLLIE_ACCESS_TOKEN",
    "MOLLIE_OAUTH_TOKEN",
    "MOLLIE_API_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_API_KEY",
    "OPENAI_API_KEY",
    "CLICKUP_API_TOKEN",
    "GOOGLE_MAPS_API_KEY",
    "MS_GRAPH_CLIENT_ID",
    "MS_GRAPH_TENANT_ID",
    "MS_GRAPH_MAILBOX",
    "MS_GRAPH_TRANSFER_MAILBOX",
    "OUTLOOK_SENDER_EMAIL",
    "FON_TEILNEHMER_ID",
    "FON_BENUTZER_ID",
    "FON_PIN",
    "PLC_CLIENT_ID",
    "PLC_ORG_UNIT_ID",
    "PLC_ORG_UNIT_GUID",
    "PLC_TEST_CLIENT_ID",
    "PLC_TEST_ORG_UNIT_ID",
    "PLC_TEST_ORG_UNIT_GUID",
    "PLC_WSDL_URL",
    "PLC_TEST_WSDL_URL",
    "PLC_TIMEOUT_SECONDS",
    "PLC_LABEL_FORMAT_ID",
    "PLC_PAPER_LAYOUT_ID",
    "PLC_LABEL_LANGUAGE",
    "PLC_LABEL_PRINTER",
    "PLC_SHIPPER_NAME1",
    "PLC_SHIPPER_NAME2",
    "PLC_SHIPPER_STREET",
    "PLC_SHIPPER_HOUSE_NUMBER",
    "PLC_SHIPPER_ADDRESS_LINE2",
    "PLC_SHIPPER_POSTAL_CODE",
    "PLC_SHIPPER_CITY",
    "PLC_SHIPPER_COUNTRY",
    "PLC_SHIPPER_PHONE",
    "PLC_SHIPPER_EMAIL",
    "PLC_SHIPPER_EORI",
)


class SecretService:
    """Resolve and persist API secrets using Fernet-encrypted DB storage."""

    def __init__(self, config: AppConfig, repo: ApiSecretRepository | None = None) -> None:
        self._config = config
        self._repo = repo
        self._ciphertext_cache: dict[str, bytes] = {}
        self._cache_loaded = False
        self._cache_lock = RLock()

    def preload(self) -> int:
        """Warm all DB secrets in one background-friendly database query."""
        self._ensure_cache_loaded()
        return len(self._ciphertext_cache)

    def _ensure_cache_loaded(self) -> None:
        if self._cache_loaded or self._repo is None:
            return
        with self._cache_lock:
            if self._cache_loaded:
                return
            self._ciphertext_cache = self._repo.get_all_ciphertexts()
            self._cache_loaded = True

    def get_secret(self, name: str) -> str:
        """Return secret value by *name* (DB first, then config/.env fallback)."""
        key = (name or "").strip().upper()
        if not key:
            return ""

        if self._repo is not None and (self._config.fernet_master_key or "").strip():
            self._ensure_cache_loaded()
            ciphertext = self._ciphertext_cache.get(key)
            if ciphertext:
                return decrypt_secret(ciphertext, self._config.fernet_master_key)

        return self._fallback_from_config(key)

    def save_secret(self, name: str, plaintext: str) -> None:
        """Encrypt and upsert *plaintext* under *name* in DB."""
        key = (name or "").strip().upper()
        if not key:
            raise ConfigError("Secret name is empty")
        if self._repo is None:
            raise ConfigError("API secret repository is not available")
        if not (self._config.fernet_master_key or "").strip():
            raise ConfigError("FERNET_MASTER_KEY is empty")

        self._ensure_cache_loaded()
        value = (plaintext or "").strip()
        ciphertext = encrypt_secret(value, self._config.fernet_master_key)
        self._repo.upsert_ciphertext(key, ciphertext)
        with self._cache_lock:
            self._ciphertext_cache[key] = ciphertext
            self._cache_loaded = True

    @staticmethod
    def supported_keys() -> tuple[str, ...]:
        """Return sorted list of known secret keys used across the app."""
        return SUPPORTED_SECRET_KEYS

    def _fallback_from_config(self, key: str) -> str:
        if key == "SEVDESK_API_TOKEN":
            return (self._config.sevdesk.api_token or "").strip()
        if key == "WIX_API_KEY":
            return (self._config.wix.api_key or "").strip()
        if key == "WIX_SITE_ID":
            return (self._config.wix.site_id or "").strip()
        if key == "WIX_ACCOUNT_ID":
            return (self._config.wix.account_id or "").strip()
        # Generic fallback allows gradual migration of additional env tokens.
        env_value = (os.getenv(key, "") or "").strip()
        if env_value:
            return env_value
        return self._legacy_graph_fallback(key)

    def _legacy_graph_fallback(self, key: str) -> str:
        mapping = {
            "MS_GRAPH_TENANT_ID": "tenant_id",
            "MS_GRAPH_CLIENT_ID": "client_id",
            "MS_GRAPH_MAILBOX": "mailbox_user",
            "MS_GRAPH_TRANSFER_MAILBOX": "transfer_mailbox_user",
        }
        legacy_key = mapping.get(key)
        if not legacy_key:
            return ""
        config_path = self._legacy_config_path()
        if not config_path.exists():
            return ""
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        graph = payload.get("graph") if isinstance(payload, dict) else None
        if not isinstance(graph, dict):
            return ""
        return str(graph.get(legacy_key) or "").strip()

    @staticmethod
    def _legacy_config_path() -> Path:
        override = (os.getenv("XW_STUDIO_LEGACY_SEVDESK_CONFIG") or "").strip()
        if override:
            return Path(os.path.expandvars(os.path.expanduser(override)))
        repo_root = Path(__file__).resolve().parents[4]
        return repo_root.parent / "sevDesk" / "sevdesk_wix_fulfillment" / "config.json"
