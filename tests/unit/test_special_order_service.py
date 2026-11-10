from __future__ import annotations

import pytest

from xw_office.services.special_orders.service import SpecialOrderService


def test_endpoint_response_without_json_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="keine JSON-Antwort"):
        SpecialOrderService._link_from_endpoint_response(None, fallback_title="Test")


def test_endpoint_response_without_success_reports_server_error() -> None:
    with pytest.raises(RuntimeError, match="Payment Link fehlgeschlagen"):
        SpecialOrderService._link_from_endpoint_response(
            {"ok": False, "message": "Payment Link fehlgeschlagen"},
            fallback_title="Test",
        )


def test_rest_response_accepts_nested_link_and_rejects_non_object_links() -> None:
    result = SpecialOrderService._link_from_rest_response(
        {
            "paymentLink": {
                "_id": "link-1",
                "title": "Test",
                "links": {"url": "https://example.test/pay"},
            }
        },
        fallback_title="Fallback",
    )
    assert result.id == "link-1"
    assert result.url == "https://example.test/pay"

    with pytest.raises(RuntimeError, match="keinen Payment-Link-URL"):
        SpecialOrderService._link_from_rest_response(
            {"paymentLink": None}, fallback_title="Fallback"
        )
