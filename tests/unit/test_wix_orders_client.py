from __future__ import annotations

from typing import Any
import httpx

from xw_studio.services.wix.client import WixOrdersClient
from xw_studio.services.wix.order_cache import WixOrderCache


def test_pick_exact_order_match_uses_exact_number() -> None:
    orders: list[dict[str, Any]] = [
        {"id": "a", "number": "20463"},
        {"id": "b", "number": "20460"},
    ]

    picked = WixOrdersClient._pick_exact_order_match("20460", orders)  # noqa: SLF001

    assert picked.get("id") == "b"


def test_line_item_is_digital_detects_wix_item_type_flags() -> None:
    assert WixOrdersClient.line_item_is_digital({"itemType": {"preset": "DIGITAL"}})
    assert WixOrdersClient.line_item_is_digital({"physicalProperties": {"shippable": False}})
    assert WixOrdersClient.line_item_is_digital({"productType": "digital"})
    assert not WixOrdersClient.line_item_is_digital({"itemType": {"preset": "PHYSICAL"}})


def test_is_reference_digital_only_checks_all_line_items() -> None:
    class _Client(WixOrdersClient):
        def __init__(self) -> None:
            pass

        def _resolve_order(self, reference: str) -> dict[str, Any]:
            if reference == "all-digital":
                return {
                    "lineItems": [
                        {"itemType": {"preset": "DIGITAL"}},
                        {"physicalProperties": {"shippable": "false"}},
                    ]
                }
            if reference == "mixed":
                return {
                    "lineItems": [
                        {"itemType": {"preset": "DIGITAL"}},
                        {"itemType": {"preset": "PHYSICAL"}},
                    ]
                }
            return {}

    client = _Client()

    assert client.is_reference_digital_only("all-digital") is True
    assert client.is_reference_digital_only("mixed") is False
    assert client.is_reference_digital_only("missing") is False


def test_best_address_lines_prefers_shipping_then_billing() -> None:
    order_shipping = {
        "buyerInfo": {"firstName": "Max", "lastName": "Mustermann"},
        "shippingInfo": {
            "shippingDestination": {
                "addressLine1": "Musterstrasse 1",
                "postalCode": "1010",
                "city": "Wien",
                "country": "AT",
            }
        },
        "billingInfo": {
            "contactDetails": {"company": "Fallback GmbH"},
            "address": {"addressLine1": "Fallbackweg 9"},
        },
    }
    lines = WixOrdersClient.best_address_lines_from_order(order_shipping)
    assert lines[0] == "Max Mustermann"
    assert "Musterstrasse 1" in lines
    assert "AUSTRIA" in lines

    order_billing_only = {
        "billingInfo": {
            "contactDetails": {"company": "Billing GmbH"},
            "address": {
                "addressLine1": "Rechnungsweg 7",
                "postalCode": "5020",
                "city": "Salzburg",
                "country": "AT",
            },
        }
    }
    lines2 = WixOrdersClient.best_address_lines_from_order(order_billing_only)
    assert lines2[0] == "Billing GmbH"
    assert "Rechnungsweg 7" in lines2
    assert "AUSTRIA" in lines2


def test_best_address_lines_supports_nested_shipping_address_variants() -> None:
    order = {
        "shippingInfo": {
            "shipmentDetails": {
                "firstName": "Jakob",
                "lastName": "Aichberger",
            },
            "shippingDestination": {
                "address": {
                    "addressLine1": "Wolfsbacher Straße 12",
                    "postalCode": "3354",
                    "city": "Wolfsbach",
                    "countryCode": "AT",
                }
            },
        }
    }

    lines = WixOrdersClient.best_address_lines_from_order(order)

    assert lines == [
        "Jakob Aichberger",
        "Wolfsbacher Straße 12",
        "3354 Wolfsbach",
        "AUSTRIA",
    ]


def test_shipping_address_lines_include_company_and_contact_name() -> None:
    order = {
        "shippingInfo": {
            "shippingDestination": {
                "contactDetails": {
                    "firstName": "Franz",
                    "lastName": "Muster",
                    "company": "Muster Musik GmbH",
                },
                "address": {
                    "addressLine": "Hauptstrasse 9",
                    "postalCode": "8010",
                    "city": "Graz",
                    "countryCode": "AT",
                },
            }
        }
    }

    lines = WixOrdersClient.shipping_address_lines_from_order(order)

    assert lines == [
        "Muster Musik GmbH",
        "Franz Muster",
        "Hauptstrasse 9",
        "8010 Graz",
        "AUSTRIA",
    ]


def test_shipping_address_lines_translate_german_country_for_label() -> None:
    order = {
        "buyerInfo": {"firstName": "Nora", "lastName": "Nord"},
        "shippingInfo": {
            "shippingDestination": {
                "address": {
                    "addressLine": "Fjordveien 7",
                    "postalCode": "5003",
                    "city": "Bergen",
                    "countryName": "Norwegen",
                },
            }
        },
    }

    lines = WixOrdersClient.shipping_address_lines_from_order(order)

    assert lines[-1] == "NORWAY"


def test_best_address_lines_merges_structured_street_address_number() -> None:
    order = {
        "buyerInfo": {"firstName": "Florian", "lastName": "Brandner"},
        "shippingInfo": {
            "shippingDestination": {
                "streetAddress": {"name": "Auerdörfl", "number": "16", "apt": ""},
                "postalCode": "20038",
                "city": "Berchtesgaden",
                "countryCode": "DE",
            }
        },
        "billingInfo": {
            "address": {
                "streetAddress": {"name": "Auerdörfl", "number": "16"},
                "postalCode": "20038",
                "city": "Berchtesgaden",
                "countryCode": "DE",
            }
        },
    }

    lines = WixOrdersClient.best_address_lines_from_order(order)

    assert lines == [
        "Florian Brandner",
        "Auerdörfl 16",
        "20038 Berchtesgaden",
        "GERMANY",
    ]

    summary = WixOrdersClient._summary_from_order(order)  # noqa: SLF001

    assert summary["wix_shipping_street"] == "Auerdörfl 16"
    assert summary["wix_billing_street"] == "Auerdörfl 16"
    assert summary["wix_billing_city"] == "Berchtesgaden"
    assert summary["wix_billing_country"] == "Germany"


def test_physical_fulfillment_line_items_from_order_skips_digital_items() -> None:
    order = {
        "lineItems": [
            {"id": "phys-1", "quantity": 2, "itemType": {"preset": "PHYSICAL"}},
            {"id": "digital-1", "quantity": 1, "itemType": {"preset": "DIGITAL"}},
            {"id": "phys-2", "quantity": "3", "physicalProperties": {"shippable": True}},
        ]
    }

    items = WixOrdersClient._physical_fulfillment_line_items_from_order(order)  # noqa: SLF001

    assert items == [
        {"id": "phys-1", "quantity": 2},
        {"id": "phys-2", "quantity": 3},
    ]


def test_resolve_order_falls_back_to_order_number_search() -> None:
    responses = {
        "number": {"orders": []},
        "orderNumber": {
            "orders": [
                {
                    "id": "ord-1",
                    "number": "20348",
                    "orderNumber": "20348",
                    "buyerInfo": {"email": "info@example.test", "firstName": "Karl", "lastName": "Bogner"},
                }
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        if '"number"' in payload and '"orderNumber"' not in payload:
            return httpx.Response(200, json=responses["number"])
        if '"orderNumber"' in payload:
            return httpx.Response(200, json=responses["orderNumber"])
        raise AssertionError(payload)

    class _SecretService:
        def get_secret(self, name: str) -> str:
            values = {
                "WIX_API_KEY": "key",
                "WIX_SITE_ID": "site",
                "WIX_ACCOUNT_ID": "",
            }
            return values.get(name, "")

    client = WixOrdersClient(secret_service=_SecretService())  # type: ignore[arg-type]
    original_client = httpx.Client

    class _Client(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.Client = _Client  # type: ignore[assignment]
    try:
        summary = client.resolve_order_summary("20348")
    finally:
        httpx.Client = original_client  # type: ignore[assignment]

    assert summary["wix_order_number"] == "20348"
    assert summary["wix_customer_email"] == "info@example.test"


def test_resolve_order_summary_uses_persistent_cache(tmp_path, monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "orders": [
                    {
                        "id": "ord-cache-1",
                        "number": "20845",
                        "orderNumber": "20845",
                        "buyerInfo": {
                            "email": "cache@example.test",
                            "firstName": "Cache",
                            "lastName": "Kunde",
                        },
                    }
                ]
            },
        )

    class _SecretService:
        def get_secret(self, name: str) -> str:
            values = {
                "WIX_API_KEY": "key",
                "WIX_SITE_ID": "site",
                "WIX_ACCOUNT_ID": "",
            }
            return values.get(name, "")

    class _Client(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _Client)
    cache = WixOrderCache(tmp_path / "cache.sqlite")
    client = WixOrdersClient(secret_service=_SecretService(), order_cache=cache)  # type: ignore[arg-type]

    first = client.resolve_order_summary("20845")
    second = client.resolve_order_summary("20845")

    assert first["wix_customer_email"] == "cache@example.test"
    assert second["wix_customer_name"] == "Cache Kunde"
    assert calls == 1
