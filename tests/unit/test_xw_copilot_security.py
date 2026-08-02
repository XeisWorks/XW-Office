"""Tests for XW-Copilot HMAC security utilities."""
from __future__ import annotations

import time

from xw_office.services.xw_copilot.security import (
    generate_hmac_signature,
    is_within_replay_window,
    verify_hmac_signature,
)

_SECRET = "super-secret-key"
_PAYLOAD = b'{"action": "crm.lookup_contact"}'


def test_generate_and_verify_roundtrip() -> None:
    sig = generate_hmac_signature(_PAYLOAD, _SECRET)
    assert verify_hmac_signature(_PAYLOAD, sig, _SECRET) is True


def test_wrong_secret_rejected() -> None:
    sig = generate_hmac_signature(_PAYLOAD, _SECRET)
    assert verify_hmac_signature(_PAYLOAD, sig, "wrong-secret") is False


def test_tampered_payload_rejected() -> None:
    sig = generate_hmac_signature(_PAYLOAD, _SECRET)
    tampered = _PAYLOAD + b" tampered"
    assert verify_hmac_signature(tampered, sig, _SECRET) is False


def test_empty_secret_always_rejected() -> None:
    sig = generate_hmac_signature(_PAYLOAD, _SECRET)
    assert verify_hmac_signature(_PAYLOAD, sig, "") is False


def test_replay_window_accepts_fresh_timestamp() -> None:
    ts = str(time.time())
    assert is_within_replay_window(ts, max_age_seconds=300) is True


def test_replay_window_rejects_old_timestamp() -> None:
    ts = str(time.time() - 400)
    assert is_within_replay_window(ts, max_age_seconds=300) is False


def test_replay_window_rejects_invalid_timestamp() -> None:
    assert is_within_replay_window("not-a-number") is False
