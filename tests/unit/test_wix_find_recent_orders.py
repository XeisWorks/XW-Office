"""Tests for WixOrdersClient.find_recent_orders_by_contact_or_email (Lieferkorrektur spec §5).

Purely additive method — these tests monkeypatch the existing private
``_search_orders`` directly (same pattern as test_wix_orders_client.py) so
no real HTTP calls happen and no existing call site is touched.
"""
from __future__ import annotations

import datetime
from typing import Any

from xw_office.services.wix.client import WixOrdersClient
from xw_office.services.wix.order_cache import WixOrderCache


class _Secrets:
    def get_secret(self, key: str) -> str:
        return {"WIX_API_KEY": "key", "WIX_SITE_ID": "site", "WIX_ACCOUNT_ID": "account"}.get(key, "")


def _client(tmp_path) -> WixOrdersClient:
    cache = WixOrderCache(tmp_path / "cache.sqlite")
    return WixOrdersClient(secret_service=_Secrets(), order_cache=cache)  # type: ignore[arg-type]


def test_find_recent_orders_prefers_contact_id_over_email(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_search(field: str | None = None, value: str = "", *, limit: int = 100) -> list[dict[str, Any]]:
        calls.append((field or "", value))
        if field == "buyerInfo.contactId":
            return [{"id": "order-1", "number": "21900", "createdDate": "2026-08-01T00:00:00Z"}]
        return []

    monkeypatch.setattr(client, "_search_orders", fake_search)

    result = client.find_recent_orders_by_contact_or_email(contact_id="contact-1", email="a@b.com")

    assert [order["id"] for order in result] == ["order-1"]
    assert calls == [("buyerInfo.contactId", "contact-1")]


def test_find_recent_orders_falls_back_to_email_when_contact_id_empty(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_search(field: str | None = None, value: str = "", *, limit: int = 100) -> list[dict[str, Any]]:
        calls.append((field or "", value))
        if field == "buyerInfo.email":
            return [{"id": "order-2", "number": "21901", "createdDate": "2026-08-01T00:00:00Z"}]
        return []

    monkeypatch.setattr(client, "_search_orders", fake_search)

    result = client.find_recent_orders_by_contact_or_email(email="mueller@example.com")

    assert [order["id"] for order in result] == ["order-2"]
    assert calls == [("buyerInfo.email", "mueller@example.com")]


def test_find_recent_orders_excludes_source_order_and_stale_orders(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path)

    def fake_search(field: str | None = None, value: str = "", *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {"id": "source-order", "number": "21842", "createdDate": "2026-08-05T00:00:00Z"},
            {"id": "old-order", "number": "21800", "createdDate": "2026-07-01T00:00:00Z"},
            {"id": "new-order", "number": "21900", "createdDate": "2026-08-10T00:00:00Z"},
        ]

    monkeypatch.setattr(client, "_search_orders", fake_search)

    since = datetime.datetime(2026, 8, 5, tzinfo=datetime.timezone.utc)
    result = client.find_recent_orders_by_contact_or_email(
        contact_id="contact-1", since=since, exclude_order_id="source-order"
    )

    assert [order["id"] for order in result] == ["new-order"]


def test_find_recent_orders_without_credentials_returns_empty(monkeypatch) -> None:
    class _EmptySecrets:
        def get_secret(self, key: str) -> str:
            return ""

    client = WixOrdersClient(secret_service=_EmptySecrets())  # type: ignore[arg-type]
    monkeypatch.setattr(
        client, "_search_orders", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call API"))
    )

    assert client.find_recent_orders_by_contact_or_email(contact_id="x") == []
