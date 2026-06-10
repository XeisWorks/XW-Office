"""Unit tests for WixProductDetailsClient.

All tests run without network access via httpx.MockTransport.
"""
from __future__ import annotations

import json
import pytest
import httpx

from xw_studio.services.wix.product_details_client import (
    CatalogVersion,
    UpdateResult,
    WixProductDetail,
    WixProductDetailsClient,
    _parse_detail,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Secrets:
    def __init__(self, *, key: str = "test-key", site: str = "test-site") -> None:
        self._data = {"WIX_API_KEY": key, "WIX_SITE_ID": site, "WIX_ACCOUNT_ID": ""}

    def get_secret(self, name: str) -> str:
        return self._data.get(name, "")


def _client(*, key: str = "k", site: str = "s") -> WixProductDetailsClient:
    return WixProductDetailsClient(secret_service=_Secrets(key=key, site=site))  # type: ignore[arg-type]


def _client_no_creds() -> WixProductDetailsClient:
    return WixProductDetailsClient(secret_service=_Secrets(key="", site=""))  # type: ignore[arg-type]


def _make_product(pid: str = "P1", revision: str = "r1", name: str = "Test") -> dict:
    return {
        "id": pid,
        "revision": revision,
        "name": name,
        "visible": True,
        "brand": {"name": "XeisWorks"},
        "variants": [{"sku": "XW-100", "priceData": {"price": "9.99"}}],
        "weight": 0.5,
        "cost": 3.00,
        "ribbon": "NEU",
        "description": "Eine Beschreibung",
        "stock": {"quantity": 5},
        "categories": [{"id": "CAT-1"}, {"id": "CAT-2"}],
    }


# ---------------------------------------------------------------------------
# _parse_detail
# ---------------------------------------------------------------------------


def test_parse_detail_extracts_all_fields() -> None:
    raw = _make_product("P-42", revision="rev-7", name="Testprodukt")
    detail = _parse_detail(raw)

    assert detail.id == "P-42"
    assert detail.revision == "rev-7"
    assert detail.name == "Testprodukt"
    assert detail.sku == "XW-100"
    assert detail.price == pytest.approx(9.99)
    assert detail.weight == pytest.approx(0.5)
    assert detail.cost == pytest.approx(3.0)
    assert detail.ribbon == "NEU"
    assert detail.brand_name == "XeisWorks"
    assert detail.visible is True
    assert detail.inventory_quantity == 5
    assert "CAT-1" in detail.category_ids
    assert "CAT-2" in detail.category_ids


def test_parse_detail_v1_flat_layout() -> None:
    raw = {
        "id": "P-v1",
        "name": "V1 Produkt",
        "sku": "XW-V1",
        "price": "12.00",
        "visible": False,
        "brand": "OldBrand",
    }
    detail = _parse_detail(raw)
    assert detail.sku == "XW-V1"
    assert detail.price == pytest.approx(12.0)
    assert detail.visible is False
    assert detail.brand_name == "OldBrand"
    assert detail.revision == ""


# ---------------------------------------------------------------------------
# Credential checks
# ---------------------------------------------------------------------------


def test_has_credentials_false_when_no_key() -> None:
    c = _client_no_creds()
    assert c.has_credentials() is False


def test_has_credentials_true_when_key_and_site() -> None:
    c = _client()
    assert c.has_credentials() is True


def test_detect_version_returns_unknown_without_credentials() -> None:
    c = _client_no_creds()
    assert c.detect_catalog_version() == CatalogVersion.UNKNOWN


# ---------------------------------------------------------------------------
# Version detection via mock transport
# ---------------------------------------------------------------------------


def _transport_428_then_ok() -> httpx.MockTransport:
    """First call → 428 (v3 probe fails), second GET call returns product data."""
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        if "v3" in str(request.url) and "query" in str(request.url):
            return httpx.Response(428, json={"message": "CATALOG_V1"})
        return httpx.Response(200, json={"products": []})

    return httpx.MockTransport(handler)


def _transport_v3_ok() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"products": []})

    return httpx.MockTransport(handler)


def _patched_client(transport: httpx.MockTransport) -> WixProductDetailsClient:
    """Return a client that uses the mock transport for all requests."""
    original = httpx.Client

    class _MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.Client = _MockClient  # type: ignore[assignment]
    try:
        c = _client()
        c.detect_catalog_version()
    finally:
        httpx.Client = original  # type: ignore[assignment]
    return c


def test_detect_version_v1_on_428() -> None:
    original = httpx.Client
    results: list[CatalogVersion] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(428, json={"message": "CATALOG_V1"})

    class _Mock(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        results.append(c.detect_catalog_version())
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert results[0] == CatalogVersion.V1


def test_detect_version_v3_on_200() -> None:
    original = httpx.Client
    results: list[CatalogVersion] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"products": []})

    class _Mock(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        results.append(c.detect_catalog_version())
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert results[0] == CatalogVersion.V3


def test_detect_version_cached_after_first_call() -> None:
    """Second call must not go to the network again."""
    original = httpx.Client
    probe_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        probe_count[0] += 1
        return httpx.Response(200, json={"products": []})

    class _Mock(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        c.detect_catalog_version()
        c.detect_catalog_version()  # second call — should be cached
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert probe_count[0] == 1  # only one network call


# ---------------------------------------------------------------------------
# get_product
# ---------------------------------------------------------------------------


def _product_get_transport(product_data: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "query" in url:
            return httpx.Response(200, json={"products": []})  # probe/list
        return httpx.Response(200, json={"product": product_data})

    return httpx.MockTransport(handler)


def test_get_product_returns_detail() -> None:
    raw = _make_product("P-1", revision="rev-1", name="Detail Produkt")
    original = httpx.Client
    results: list[WixProductDetail | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "query" in str(request.url):
            return httpx.Response(200, json={"products": []})
        return httpx.Response(200, json={"product": raw})

    class _Mock(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        results.append(c.get_product("P-1"))
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert results[0] is not None
    assert results[0].id == "P-1"
    assert results[0].revision == "rev-1"
    assert results[0].name == "Detail Produkt"


def test_get_product_returns_none_without_credentials() -> None:
    c = _client_no_creds()
    assert c.get_product("any-id") is None


def test_get_product_revision_returns_empty_on_failure() -> None:
    original = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    class _Mock(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        rev = c.get_product_revision("missing-id")
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert rev == ""


# ---------------------------------------------------------------------------
# Single-field updates — v3
# ---------------------------------------------------------------------------


def _make_patch_recorder() -> tuple[list[dict], httpx.MockTransport]:
    """Return (captured_patches, transport) for intercepting PATCH calls."""
    patches: list[dict] = []
    raw_product = _make_product("P-1", revision="rev-9", name="Test")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "PATCH":
            body = json.loads(request.content) if request.content else {}
            patches.append({"url": url, "body": body})
            return httpx.Response(200, json={"product": raw_product})
        # v3 query probe
        if "query" in url:
            return httpx.Response(200, json={"products": []})
        # GET for revision
        return httpx.Response(200, json={"product": raw_product})

    return patches, httpx.MockTransport(handler)


def _with_transport(transport: httpx.MockTransport) -> type:
    class _Mock(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    return _Mock


def test_update_price_v3_sends_correct_payload() -> None:
    patches, transport = _make_patch_recorder()
    original = httpx.Client
    httpx.Client = _with_transport(transport)  # type: ignore[assignment]
    try:
        c = _client()
        result = c.update_product_price("P-1", price=24.99)
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert result.succeeded == 1
    assert result.failed == 0
    assert patches, "expected at least one PATCH"
    body = patches[-1]["body"]["product"]
    # v3: revision must be present
    assert "revision" in body
    # price via priceData
    assert "priceData" in body
    assert float(body["priceData"]["price"]) == pytest.approx(24.99)


def test_update_visible_v3_sends_boolean() -> None:
    patches, transport = _make_patch_recorder()
    original = httpx.Client
    httpx.Client = _with_transport(transport)  # type: ignore[assignment]
    try:
        c = _client()
        result = c.update_product_visible("P-1", visible=False)
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert result.succeeded == 1
    body = patches[-1]["body"]["product"]
    assert body["visible"] is False
    assert "revision" in body


def test_update_brand_v3_sends_nested_brand_object() -> None:
    patches, transport = _make_patch_recorder()
    original = httpx.Client
    httpx.Client = _with_transport(transport)  # type: ignore[assignment]
    try:
        c = _client()
        result = c.update_product_brand("P-1", brand_name="Neumarke")
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert result.succeeded == 1
    body = patches[-1]["body"]["product"]
    assert isinstance(body.get("brand"), dict)
    assert body["brand"]["name"] == "Neumarke"


def test_update_ribbon_v3() -> None:
    patches, transport = _make_patch_recorder()
    original = httpx.Client
    httpx.Client = _with_transport(transport)  # type: ignore[assignment]
    try:
        c = _client()
        result = c.update_product_ribbon("P-1", ribbon="SALE")
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert result.succeeded == 1
    body = patches[-1]["body"]["product"]
    assert body.get("ribbon") == "SALE"


# ---------------------------------------------------------------------------
# Single-field updates — v1 (patch after 428 probe)
# ---------------------------------------------------------------------------


def _make_v1_patch_recorder() -> tuple[list[dict], httpx.MockTransport]:
    patches: list[dict] = []
    raw_product = _make_product("P-2", revision="", name="V1 Test")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        # v3 query probe returns 428
        if "v3" in url and "query" in url:
            return httpx.Response(428, json={"message": "CATALOG_V1"})
        if request.method == "PATCH":
            body = json.loads(request.content) if request.content else {}
            patches.append({"url": url, "body": body})
            return httpx.Response(200, json={"product": raw_product})
        return httpx.Response(200, json={"product": raw_product})

    return patches, httpx.MockTransport(handler)


def test_update_price_v1_no_revision() -> None:
    patches, transport = _make_v1_patch_recorder()
    original = httpx.Client
    httpx.Client = _with_transport(transport)  # type: ignore[assignment]
    try:
        c = _client()
        result = c.update_product_price("P-2", price=14.50)
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert result.succeeded == 1
    body = patches[-1]["body"]["product"]
    # v1: no revision
    assert "revision" not in body
    assert "priceData" in body


def test_update_compare_at_price_v1_uses_salePrice_field() -> None:
    patches, transport = _make_v1_patch_recorder()
    original = httpx.Client
    httpx.Client = _with_transport(transport)  # type: ignore[assignment]
    try:
        c = _client()
        result = c.update_product_compare_at_price("P-2", compare_at_price=9.99)
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert result.succeeded == 1
    body = patches[-1]["body"]["product"]
    # v1 uses salePrice (via priceData.compareAtPrice in our impl)
    assert "revision" not in body
    assert "priceData" in body


# ---------------------------------------------------------------------------
# Bulk property update — v3
# ---------------------------------------------------------------------------


def test_bulk_update_property_v3_sends_correct_payload() -> None:
    bulk_calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "query" in url:
            return httpx.Response(200, json={"products": []})
        if "bulkUpdateProperty" in url:
            body = json.loads(request.content) if request.content else {}
            bulk_calls.append(body)
            return httpx.Response(200, json={"results": [{"id": pid} for pid in body.get("productIds", [])]})
        return httpx.Response(200, json={})

    original = httpx.Client

    class _Mock(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        result = c.bulk_update_property(["P-1", "P-2", "P-3"], field="visible", value=False)
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert len(bulk_calls) == 1
    call = bulk_calls[0]
    assert call["property"] == "visible"
    assert call["value"] is False
    assert set(call["productIds"]) == {"P-1", "P-2", "P-3"}
    assert result.succeeded == 3
    assert result.failed == 0


def test_bulk_update_property_v3_chunks_at_100() -> None:
    bulk_calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "query" in str(request.url):
            return httpx.Response(200, json={"products": []})
        if "bulkUpdateProperty" in str(request.url):
            body = json.loads(request.content) if request.content else {}
            bulk_calls.append(body)
            return httpx.Response(200, json={"results": [{"id": p} for p in body.get("productIds", [])]})
        return httpx.Response(200, json={})

    original = httpx.Client

    class _Mock(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        ids = [f"P-{i}" for i in range(150)]  # more than the 100-per-call limit
        result = c.bulk_update_property(ids, field="ribbon", value="SALE")
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert len(bulk_calls) == 2  # 150 / 100 = 2 chunks
    assert result.requested == 150
    assert result.succeeded == 150
    assert result.failed == 0


# ---------------------------------------------------------------------------
# Bulk property update — v1 fallback (loop)
# ---------------------------------------------------------------------------


def test_bulk_update_property_v1_falls_back_to_loop() -> None:
    patch_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "v3" in url and "query" in url:
            return httpx.Response(428, json={"message": "CATALOG_V1"})
        if request.method == "PATCH":
            patch_count[0] += 1
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    original = httpx.Client

    class _Mock(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        result = c.bulk_update_property(["P-1", "P-2"], field="name", value="Neuer Name")
    finally:
        httpx.Client = original  # type: ignore[assignment]

    # v1 fallback: one PATCH per product
    assert patch_count[0] == 2
    assert result.requested == 2
    assert result.succeeded == 2


# ---------------------------------------------------------------------------
# Bulk adjust price — v3
# ---------------------------------------------------------------------------


def test_bulk_adjust_price_v3_sends_adjust_payload() -> None:
    adjust_calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "query" in url:
            return httpx.Response(200, json={"products": []})
        if "bulkAdjustProperty" in url:
            body = json.loads(request.content) if request.content else {}
            adjust_calls.append(body)
            return httpx.Response(200, json={"results": [{"id": p} for p in body.get("productIds", [])]})
        return httpx.Response(200, json={})

    original = httpx.Client

    class _Mock(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        result = c.bulk_adjust_price(["P-1", "P-2"], adjust_type="PERCENTAGE", adjust_value=10.0)
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert len(adjust_calls) == 1
    call = adjust_calls[0]
    assert call["adjustValue"] == 10.0
    assert call["adjustType"] == "PERCENTAGE"
    assert call["property"] == "price"
    assert result.succeeded >= 1


# ---------------------------------------------------------------------------
# Payload builders — pure logic, no HTTP
# ---------------------------------------------------------------------------


def test_build_v3_payload_price() -> None:
    payload = WixProductDetailsClient._build_v3_payload("price", 19.99, "rev-1")
    inner = payload["product"]
    assert inner["revision"] == "rev-1"
    assert inner["priceData"]["price"] == pytest.approx(19.99)


def test_build_v3_payload_visible_false() -> None:
    payload = WixProductDetailsClient._build_v3_payload("visible", False, "rev-2")
    assert payload["product"]["visible"] is False
    assert payload["product"]["revision"] == "rev-2"


def test_build_v3_payload_brand_is_nested() -> None:
    payload = WixProductDetailsClient._build_v3_payload("brand", "NewBrand", "r")
    brand = payload["product"]["brand"]
    assert isinstance(brand, dict)
    assert brand["name"] == "NewBrand"


def test_build_v1_payload_no_revision() -> None:
    payload = WixProductDetailsClient._build_v1_payload("price", 5.00)
    inner = payload["product"]
    assert "revision" not in inner
    assert "priceData" in inner


def test_build_v1_payload_compare_at_maps_to_salePrice() -> None:
    """v1 uses priceData.compareAtPrice path (consistent with our impl)."""
    payload = WixProductDetailsClient._build_v1_payload("compareAtPrice", 7.99)
    inner = payload["product"]
    assert "priceData" in inner
    assert "revision" not in inner


def test_coerce_value_rounds_floats() -> None:
    assert WixProductDetailsClient._coerce_value("price", 3.141592) == pytest.approx(3.14)
    assert WixProductDetailsClient._coerce_value("weight", "1.234") == pytest.approx(1.23)


def test_coerce_value_visible_from_string() -> None:
    assert WixProductDetailsClient._coerce_value("visible", "true") is True
    assert WixProductDetailsClient._coerce_value("visible", "0") is False
    assert WixProductDetailsClient._coerce_value("visible", "ja") is True


def test_coerce_value_categories_from_csv() -> None:
    result = WixProductDetailsClient._coerce_value("categories", "CAT-1, CAT-2 , CAT-3")
    assert result == ["CAT-1", "CAT-2", "CAT-3"]


def test_v1_field_name_mapping() -> None:
    assert WixProductDetailsClient._v1_field_name("compareAtPrice") == "salePrice"
    assert WixProductDetailsClient._v1_field_name("cost") == "costOfGoodsSold"
    assert WixProductDetailsClient._v1_field_name("categories") == "categoryIds"
    assert WixProductDetailsClient._v1_field_name("price") == "price"
    assert WixProductDetailsClient._v1_field_name("visible") == "visible"


def test_v3_field_name_mapping() -> None:
    assert WixProductDetailsClient._v3_field_name("compareAtPrice") == "compareAtPrice"
    assert WixProductDetailsClient._v3_field_name("compare_at_price") == "compareAtPrice"
    assert WixProductDetailsClient._v3_field_name("cost") == "cost"
    assert WixProductDetailsClient._v3_field_name("weight") == "weight"


# ---------------------------------------------------------------------------
# Error resilience
# ---------------------------------------------------------------------------


def test_update_single_returns_failure_result_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "query" in str(request.url):
            return httpx.Response(200, json={"products": []})
        if request.method == "PATCH":
            return httpx.Response(500, json={"message": "Internal Server Error"})
        return httpx.Response(200, json={"product": _make_product()})

    original = httpx.Client

    class _Mock(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        result = c.update_product_name("P-1", name="Fail")
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert result.failed >= 1
    assert result.succeeded == 0


def test_bulk_update_property_v3_partial_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "query" in str(request.url):
            return httpx.Response(200, json={"products": []})
        if "bulkUpdateProperty" in str(request.url):
            body = json.loads(request.content) if request.content else {}
            ids = body.get("productIds", [])
            results = [
                {"id": ids[0]},  # success
                {"id": ids[1], "error": "product not found"},  # failure
            ]
            return httpx.Response(200, json={"results": results})
        return httpx.Response(200, json={})

    original = httpx.Client

    class _Mock(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    httpx.Client = _Mock  # type: ignore[assignment]
    try:
        c = _client()
        result = c.bulk_update_property(["P-ok", "P-fail"], field="visible", value=True)
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert result.succeeded == 1
    assert result.failed == 1
    assert len(result.errors) == 1
