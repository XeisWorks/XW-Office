"""Tests for the read-only sevDesk TaxSetClient."""
from __future__ import annotations

import httpx

from xw_office.core.config import AppConfig
from xw_office.services.http_client import SevdeskConnection
from xw_office.services.sevdesk.tax_set_client import TaxSetClient


def test_find_by_text_matches_live_tax_set() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/TaxSet" in str(request.url)
        return httpx.Response(
            200,
            json={
                "objects": [
                    {"id": "1", "objectName": "TaxSet", "text": "Deutsche MwSt. 7%"},
                    {"id": "2", "objectName": "TaxSet", "text": "Steuerfreie Ausfuhrlieferung (§ 7 UStG 1994)"},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    conn = SevdeskConnection(client=client, config=AppConfig())
    tax_sets = TaxSetClient(conn)

    found = tax_sets.find_by_text("Deutsche MwSt. 7%")
    assert found is not None
    assert found.id == "1"

    missing = tax_sets.find_by_text("Nicht vorhanden")
    assert missing is None


def test_list_tax_sets_caches_by_default() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"objects": [{"id": "1", "text": "Deutsche MwSt. 7%"}]})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    conn = SevdeskConnection(client=client, config=AppConfig())
    tax_sets = TaxSetClient(conn)

    tax_sets.list_tax_sets()
    tax_sets.list_tax_sets()
    assert call_count == 1

    tax_sets.list_tax_sets(refresh_cache=True)
    assert call_count == 2


def test_list_tax_sets_returns_empty_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    conn = SevdeskConnection(client=client, config=AppConfig())
    tax_sets = TaxSetClient(conn)

    assert tax_sets.list_tax_sets() == []
