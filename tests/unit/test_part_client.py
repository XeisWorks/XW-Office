"""Tests for sevDesk Part client."""
from __future__ import annotations

from typing import Any

from xw_office.services.sevdesk.part_client import PartClient


class _ResponseStub:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _ConnStub:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = pages
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, path: str, **kwargs: Any) -> _ResponseStub:
        params = kwargs.get("params") or {}
        self.calls.append((path, dict(params)))
        offset = int(params.get("offset") or 0)
        index = offset // 100
        payload = self._pages[index] if index < len(self._pages) else {"objects": []}
        return _ResponseStub(payload)


def test_list_parts_parses_rows() -> None:
    conn = _ConnStub(
        [
            {
                "objects": [
                    {
                        "id": "10",
                        "partNumber": "XW-4-001",
                        "name": "Etuede A",
                        "price": "19.90",
                        "stock": "7",
                    }
                ]
            }
        ]
    )
    client = PartClient(conn)  # type: ignore[arg-type]

    rows = client.list_parts()

    assert len(rows) == 1
    assert rows[0].id == "10"
    assert rows[0].sku == "XW-4-001"
    assert rows[0].price_eur == "19.90"
    assert rows[0].stock_qty == 7


def test_list_parts_paginates() -> None:
    first_page = {"objects": [{"id": str(i), "partNumber": f"SKU-{i}"} for i in range(100)]}
    second_page = {"objects": [{"id": "101", "partNumber": "SKU-101"}]}
    conn = _ConnStub([first_page, second_page])
    client = PartClient(conn)  # type: ignore[arg-type]

    rows = client.list_parts()

    assert len(rows) == 101
    assert len(conn.calls) == 2
    assert conn.calls[0][0] == "/Part"
    assert conn.calls[1][1]["offset"] == 100


def test_list_parts_uses_cache_without_extra_http_calls() -> None:
    conn = _ConnStub(
        [
            {
                "objects": [
                    {
                        "id": "10",
                        "partNumber": "XW-4-001",
                        "name": "Etuede A",
                    }
                ]
            }
        ]
    )
    client = PartClient(conn)  # type: ignore[arg-type]

    first = client.list_parts(refresh_cache=True)
    second = client.list_parts()

    assert len(first) == 1
    assert len(second) == 1
    assert len(conn.calls) == 1
    assert client.parts_cache_updated_at is not None


def test_list_parts_without_refresh_does_not_update_cache_timestamp() -> None:
    conn = _ConnStub(
        [
            {
                "objects": [
                    {
                        "id": "11",
                        "partNumber": "XW-4-002",
                        "name": "Etuede B",
                    }
                ]
            }
        ]
    )
    client = PartClient(conn)  # type: ignore[arg-type]

    rows = client.list_parts()

    assert len(rows) == 1
    assert client.parts_cache_updated_at is None