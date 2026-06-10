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
