"""Fernet helpers for encrypting API tokens persisted in the database."""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from xw_office.core.exceptions import ConfigError

logger = logging.getLogger(__name__)


def _fernet_from_key(master_key: str) -> Fernet:
    key = (master_key or "").strip().encode("utf-8")
    if not key:
        raise ConfigError("FERNET_MASTER_KEY is empty")
    return Fernet(key)


def encrypt_secret(plaintext: str, master_key: str) -> bytes:
    """Encrypt *plaintext* using URL-safe Fernet key from env/config."""
    return _fernet_from_key(master_key).encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes, master_key: str) -> str:
    """Decrypt Fernet *ciphertext*; raises ConfigError on bad key or corrupt data."""
    try:
        return _fernet_from_key(master_key).decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        logger.warning("Fernet decrypt failed: %s", exc)
        raise ConfigError("Could not decrypt secret — check FERNET_MASTER_KEY") from exc
