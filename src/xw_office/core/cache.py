"""Generic TTL cache with explicit invalidation."""
from __future__ import annotations

import time
from typing import Any, TypeVar

T = TypeVar("T")


class CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl_seconds: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl_seconds


class TtlCache:
    """Simple in-memory cache with per-key TTL.

    Thread safety is not guaranteed; intended for use from the Qt main thread
    or behind a lock if shared across workers.
    """

    def __init__(self, default_ttl: float = 180.0) -> None:
        self._default_ttl = default_ttl
        self._store: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None or time.monotonic() > entry.expires_at:
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        self._store[key] = CacheEntry(value, ttl or self._default_ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
