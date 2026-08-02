"""Refund flow tests (mocked, no live API)."""
from __future__ import annotations

from typing import Any

from xw_office.services.sevdesk.refund_client import SevDeskRefundClient
from xw_office.services.wix.client import WixOrdersClient


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.content = b"{}"

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def post(self, path: str, **kwargs: object) -> _FakeResponse:
        body = kwargs if isinstance(kwargs, dict) else {}
        self.calls.append(("post", path, body))
        if path.endswith("/cancelInvoice"):
            return _FakeResponse({"objects": {"invoice": {"id": "1", "status": "cancelled"}}})
        return _FakeResponse({"objects": {"creditNote": {"id": "99"}}})


def test_sevdesk_refund_client_cancel_invoice_calls_endpoint() -> None:
    conn = _FakeConnection()
    client = SevDeskRefundClient(conn)  # type: ignore[arg-type]

    payload = client.cancel_invoice("123")

    assert payload
    assert conn.calls[0][0] == "post"
    assert conn.calls[0][1] == "/Invoice/123/cancelInvoice"


def test_wix_refund_full_order_builds_payment_refunds(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    wix = WixOrdersClient(secret_service=None)

    monkeypatch.setattr(wix, "has_credentials", lambda: True)
    monkeypatch.setattr(wix, "_resolve_order", lambda _ref: {"id": "order-1"})
    monkeypatch.setattr(
        wix,
        "get_order_refundability",
        lambda _order_id: {
            "payments": [
                {
                    "refundable": True,
                    "payment": {"paymentId": "pay-1"},
                    "availableRefundAmount": {"amount": "12.34"},
                },
                {
                    "refundable": False,
                    "payment": {"paymentId": "pay-2"},
                    "availableRefundAmount": {"amount": "99.99"},
                },
            ]
        },
    )

    captured: dict[str, Any] = {}

    def _fake_refund(order_id: str, payment_refunds: list[dict[str, Any]], **kwargs: object) -> dict[str, Any]:
        captured["order_id"] = order_id
        captured["payment_refunds"] = payment_refunds
        captured["kwargs"] = kwargs
        return {"refund": "ok"}

    monkeypatch.setattr(wix, "refund_order_payments", _fake_refund)

    result = wix.refund_full_order("RE-123", send_customer_email=True, customer_reason="Test")

    assert result == {"refund": "ok"}
    assert captured["order_id"] == "order-1"
    assert captured["payment_refunds"] == [{"paymentId": "pay-1", "amount": {"amount": "12.34"}}]
    assert captured["kwargs"]["send_customer_email"] is True


def test_wix_refund_full_order_returns_empty_when_not_refundable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    wix = WixOrdersClient(secret_service=None)

    monkeypatch.setattr(wix, "has_credentials", lambda: True)
    monkeypatch.setattr(wix, "_resolve_order", lambda _ref: {"id": "order-1"})
    monkeypatch.setattr(wix, "get_order_refundability", lambda _order_id: {"payments": []})

    result = wix.refund_full_order("RE-123")

    assert result == {}
