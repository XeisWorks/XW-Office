from __future__ import annotations

import httpx

from xw_office.services.wix.client import WixProductsClient


class _SecretService:
    def __init__(self, *, key: str, site: str, account: str = "") -> None:
        self._values = {
            "WIX_API_KEY": key,
            "WIX_SITE_ID": site,
            "WIX_ACCOUNT_ID": account,
        }

    def get_secret(self, name: str) -> str:
        return self._values.get(name, "")


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
                            "revision": "rev-1",
                            "lastUpdatedDate": "2026-09-18T08:00:00Z",
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
    assert rows[0].revision == "rev-1"
    assert rows[0].updated_at == "2026-09-18T08:00:00Z"


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
    assert any(
        '"offset":100' in call["payload"] or '"offset": 100' in call["payload"] for call in calls
    )
    assert len(rows) == 101
    assert rows[-1].sku == "XW-101"


def test_list_products_reader_query_includes_hidden_products_and_variants() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/stores/v3/catalog/products/query") or url.endswith(
            "/stores/v3/products/query"
        ):
            return httpx.Response(404, text="not found")
        if not url.endswith("/stores-reader/v1/products/query"):
            return httpx.Response(404, text="unknown")
        payload = request.read().decode("utf-8")
        import json

        payloads.append(json.loads(payload))
        return httpx.Response(
            200,
            json={
                "products": [
                    {
                        "id": "hidden-1",
                        "name": "Verstecktes Produkt",
                        "visible": False,
                        "variants": [
                            {"variant": {"sku": "XW-101.3"}},
                            {"variant": {"sku": "XW-101.4"}},
                        ],
                    }
                ],
                "pagingMetadata": {"hasNext": False},
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
        rows = client.list_products(include_hidden=True)
    finally:
        httpx.Client = original_client  # type: ignore[assignment]

    assert rows[0].sku == "XW-101.3"
    assert rows[0].all_skus == ("XW-101.3", "XW-101.4")
    assert payloads
    assert payloads[0]["includeHiddenProducts"] is True
    assert payloads[0]["includeVariants"] is True


def test_reader_variant_keeps_its_id_sku_and_option_name() -> None:
    from xw_office.services.wix.client import _parse_product

    product = _parse_product(
        {
            "id": "bh-polka",
            "name": "BH Polka",
            "variants": [
                {
                    "id": "wix-variant-small",
                    "choices": {"Besetzung": "Kleine Besetzung"},
                    "variant": {"sku": "XW-6012"},
                }
            ],
        }
    )

    assert product.all_skus == ("XW-6012",)
    assert product.variants[0].id == "wix-variant-small"
    assert product.variants[0].sku == "XW-6012"
    assert product.variants[0].name == "Besetzung: Kleine Besetzung"
