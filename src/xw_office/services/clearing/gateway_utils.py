"""Shared parsing and HTTP settings for clearing gateways."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

VIENNA = ZoneInfo("Europe/Vienna")
TIMEOUT = httpx.Timeout(45.0, connect=10.0)


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        raw = int(value)
        if raw >= 10**12:
            raw //= 1000
        dt = datetime.fromtimestamp(raw, tz=timezone.utc)
    elif isinstance(value, str) and value.isdigit():
        raw = int(value)
        if raw >= 10**12:
            raw //= 1000
        dt = datetime.fromtimestamp(raw, tz=timezone.utc)
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(VIENNA)
