"""Tests for TTL cache."""
import time

from xw_office.core.cache import TtlCache


def test_set_and_get() -> None:
    cache = TtlCache(default_ttl=10)
    cache.set("key", "value")
    assert cache.get("key") == "value"


def test_expired_entry_returns_none() -> None:
    cache = TtlCache(default_ttl=0.01)
    cache.set("key", "value")
    time.sleep(0.02)
    assert cache.get("key") is None


def test_invalidate() -> None:
    cache = TtlCache()
    cache.set("key", "value")
    cache.invalidate("key")
    assert cache.get("key") is None


def test_clear() -> None:
    cache = TtlCache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None
