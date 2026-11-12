from __future__ import annotations

import httpx

from xw_office.services.wix.data_client import WixDataClient


class _Secrets:
    def get_secret(self, key: str) -> str:
        return "test-site" if key == "WIX_SITE_ID" else "test-key"


def test_query_all_items_accepts_missing_paging_metadata(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("WIX_API_KEY_DATA", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"dataItems": [{"id": "item-1", "data": {"title": "Cover"}}]},
        )

    client = WixDataClient(_Secrets(), transport=httpx.MockTransport(handler))  # type: ignore[arg-type]

    assert client.query_all_items("covers", limit=10) == [{"title": "Cover", "_id": "item-1"}]
