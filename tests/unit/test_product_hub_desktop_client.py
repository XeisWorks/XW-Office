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
