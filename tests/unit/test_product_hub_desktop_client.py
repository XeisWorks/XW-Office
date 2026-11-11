import httpx
import pytest

from xw_office.services.product_hub.desktop_client import (
    ProductHubDesktopClient,
    ProductHubDesktopClientError,
)


def test_desktop_client_uses_bearer_auth_and_returns_v1_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer desktop-token"
        assert request.url.path == "/api/v1/desktop/products/product-1/snapshot"
        return httpx.Response(
            200,
            json={
                "contract_version": "v1",
                "product": {"id": "product-1", "sku": "XW-1"},
                "variants": [{"id": "variant-1", "sku": "XW-1", "prices": []}],
                "assets": [],
            },
        )

    client = ProductHubDesktopClient(
        base_url="https://hub.example", token="desktop-token", transport=httpx.MockTransport(handler)
    )
    snapshot = client.get_product_snapshot("product-1")

    assert snapshot.product["id"] == "product-1"
    assert snapshot.variants[0]["id"] == "variant-1"


def test_desktop_client_can_resolve_a_snapshot_by_sku() -> None:
    client = ProductHubDesktopClient(
        base_url="https://hub.example",
        token="desktop-token",
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200,
            json={"contract_version": "v1", "product": {"id": "product-1"}, "variants": [], "assets": []},
        )),
    )
    assert client.get_product_snapshot_by_sku("XW 1").contract_version == "v1"


def test_desktop_client_batches_and_normalizes_skus() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/api/v1/desktop/products/snapshots/batch"
        skus = request.read().decode("utf-8")
        assert '"XW-1"' in skus
        return httpx.Response(
            200,
            json={
                "XW-1": {
                    "contract_version": "v1",
                    "product": {"id": "product-1"},
                    "variants": [],
                    "assets": [],
                }
            },
        )

    client = ProductHubDesktopClient(
        base_url="https://hub.example", token="desktop-token", transport=httpx.MockTransport(handler)
    )

    result = client.get_product_snapshots_by_skus([" xw-1 ", "XW-1", ""])

    assert len(requests) == 1
    assert result["XW-1"].product["id"] == "product-1"


def test_desktop_client_chunks_snapshot_batches_at_one_hundred_skus() -> None:
    request_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        skus = json.loads(request.read())["skus"]
        request_sizes.append(len(skus))
        return httpx.Response(
            200,
            json={
                sku: {
                    "contract_version": "v1",
                    "product": {"id": sku},
                    "variants": [],
                    "assets": [],
                }
                for sku in skus
            },
        )

    client = ProductHubDesktopClient(
        base_url="https://hub.example", token="desktop-token", transport=httpx.MockTransport(handler)
    )

    result = client.get_product_snapshots_by_skus([f"XW-{index}" for index in range(101)])

    assert request_sizes == [100, 1]
    assert len(result) == 101


def test_desktop_client_rejects_missing_configuration_and_unknown_contract() -> None:
    with pytest.raises(ProductHubDesktopClientError, match="nicht konfiguriert"):
        ProductHubDesktopClient(base_url="", token="").get_product_snapshot("product-1")

    client = ProductHubDesktopClient(
        base_url="https://hub.example",
        token="desktop-token",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"contract_version": "v2"})),
    )
    with pytest.raises(ProductHubDesktopClientError, match="Inkompatibler"):
        client.get_product_snapshot("product-1")
