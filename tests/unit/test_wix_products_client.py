from __future__ import annotations

import httpx

from xw_studio.services.wix.client import WixProductsClient


class _SecretService:
    def __init__(self, *, key: str, site: str, account: str = "") -> None:
        self._values = {
            "WIX_API_KEY": key,
            "WIX_SITE_ID": site,
            "WIX_ACCOUNT_ID": account,
        }

    def get_secret(self, name: str) -> str:
        return self._values.get(name, "")


def test_brand_endpoints_selfcheck_without_credentials() -> None:
    client = WixProductsClient(secret_service=_SecretService(key="", site=""))  # type: ignore[arg-type]

    report = client.brand_endpoints_selfcheck()

    assert report["has_credentials"] is False
    assert report["query_ok"] is False
    assert report["preferred_query_endpoint"] == ""
    assert report["reachable_query_endpoints"] == 0
    assert report["checks"] == []


def test_brand_endpoints_selfcheck_picks_first_working_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/stores/v3/brands/query"):
            return httpx.Response(404, text="nope")
        if str(request.url).endswith("/stores/v3/catalog/brands/query"):
            return httpx.Response(200, json={"brands": [{"id": "b1", "name": "XW"}]})
        return httpx.Response(503, text="unavailable")

    original_client = httpx.Client

    class _Client(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.Client = _Client  # type: ignore[assignment]
    try:
        client = WixProductsClient(secret_service=_SecretService(key="k", site="s"))  # type: ignore[arg-type]
        report = client.brand_endpoints_selfcheck()
    finally:
        httpx.Client = original_client  # type: ignore[assignment]

    assert report["has_credentials"] is True
    assert report["query_ok"] is True
    assert report["preferred_query_endpoint"].endswith("/stores/v3/catalog/brands/query")
    assert report["reachable_query_endpoints"] == 1
    checks = report["checks"]
    assert isinstance(checks, list)
    assert len(checks) >= 2
    assert any(bool(item.get("parsed_list")) for item in checks if isinstance(item, dict))


def test_list_products_uses_fallback_query_endpoint() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.endswith("/stores/v3/catalog/products/query"):
            return httpx.Response(404, text="not found")
        if url.endswith("/stores/v3/products/query"):
            return httpx.Response(
                200,
                json={
                    "products": [
                        {
                            "id": "p-1",
                            "name": "Produkt A",
                            "sku": "XW-1",
                            "brand": {"id": "b-1", "name": "Marke"},
                            "visible": True,
                            "stock": {"quantity": 7},
                        }
                    ]
                },
            )
        return httpx.Response(404, text="unknown")

    original_client = httpx.Client

    class _Client(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.Client = _Client  # type: ignore[assignment]
    try:
        client = WixProductsClient(secret_service=_SecretService(key="k", site="s"))  # type: ignore[arg-type]
        rows = client.list_products()
    finally:
        httpx.Client = original_client  # type: ignore[assignment]

    assert any(url.endswith("/stores/v3/catalog/products/query") for url in calls)
    assert any(url.endswith("/stores/v3/products/query") for url in calls)
    assert len(rows) == 1
    assert rows[0].id == "p-1"
    assert rows[0].sku == "XW-1"


def test_list_products_paginates_with_has_next_and_offset_without_cursor() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        payload = request.read().decode("utf-8")
        calls.append({"url": url, "payload": payload})

        if url.endswith("/stores/v3/catalog/products/query"):
            return httpx.Response(404, text="not found")

        if not url.endswith("/stores/v3/products/query"):
            return httpx.Response(404, text="unknown")

        if '"offset":100' in payload or '"offset": 100' in payload:
            return httpx.Response(
                200,
                json={
                    "products": [
                        {
                            "id": "p-101",
                            "name": "Produkt 101",
                            "sku": "XW-101",
                            "visible": True,
                            "stock": {"quantity": 1},
                        }
                    ],
                    "pagingMetadata": {"hasNext": False},
                },
            )

        products = [
            {
                "id": f"p-{idx}",
                "name": f"Produkt {idx}",
                "sku": f"XW-{idx}",
                "visible": True,
                "stock": {"quantity": 1},
            }
            for idx in range(1, 101)
        ]
        return httpx.Response(
            200,
            json={
                "products": products,
                "pagingMetadata": {"hasNext": True},
            },
        )

    original_client = httpx.Client

    class _Client(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.Client = _Client  # type: ignore[assignment]
    try:
        client = WixProductsClient(secret_service=_SecretService(key="k", site="s"))  # type: ignore[arg-type]
        rows = client.list_products()
    finally:
        httpx.Client = original_client  # type: ignore[assignment]

    assert any(call["url"].endswith("/stores/v3/products/query") for call in calls)
    assert any('"offset":100' in call["payload"] or '"offset": 100' in call["payload"] for call in calls)
    assert len(rows) == 101
    assert rows[-1].sku == "XW-101"
