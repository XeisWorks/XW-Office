"""HMAC signature utilities for XW-Copilot webhook ingress security."""
from __future__ import annotations

import hashlib
import hmac
import time


def generate_hmac_signature(payload_bytes: bytes, secret: str) -> str:
    """Return a hex-encoded HMAC-SHA256 signature for *payload_bytes*.

    Use this on the Outlook add-in side to sign outgoing requests.
    """
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


def verify_hmac_signature(payload_bytes: bytes, signature: str, secret: str) -> bool:
    """Return True if *signature* matches a fresh HMAC-SHA256 over *payload_bytes*.

    Uses ``hmac.compare_digest`` to prevent timing attacks.
    """
    if not secret:
        return False
    expected = generate_hmac_signature(payload_bytes, secret)
    return hmac.compare_digest(expected, signature)


def is_within_replay_window(timestamp_str: str, max_age_seconds: int = 300) -> bool:
    """Return True if *timestamp_str* (Unix epoch string) is within the replay window.

    Rejects requests older than *max_age_seconds* (default 5 minutes).
    """
    try:
        ts = float(timestamp_str)
    except ValueError:
        return False
    age = abs(time.time() - ts)
    return age <= max_age_seconds
