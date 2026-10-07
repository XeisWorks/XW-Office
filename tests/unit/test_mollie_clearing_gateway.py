"""Payment-first Mollie clearing regression tests."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest

from xw_office.services.clearing.gateways import MollieClearingGateway
from xw_office.services.clearing.models import (
    InvoiceRecord,
    MatchStatus,
    SevdeskTransaction,
    TransactionKind,
    money,
)
from xw_office.services.clearing.service import PaymentClearingService

VIENNA = ZoneInfo("Europe/Vienna")
START = datetime(2026, 9, 1, tzinfo=VIENNA)
END = datetime(2026, 10, 1, tzinfo=VIENNA)


def _payment(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "tr_standalone",
        "status": "paid",
        "createdAt": "2026-08-01T12:00:00Z",
        "paidAt": "2026-09-10T12:00:00Z",
        "amount": {"currency": "EUR", "value": "29.90"},
        "metadata": {"wix_transaction_id": "wix_payment"},
        **overrides,
    }


def _mock_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    original_client = httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return original_client(*args, **kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", factory)


def _empty_resource(request: httpx.Request) -> httpx.Response:
    key = request.url.path.rsplit("/", 1)[-1]
    assert key in {"refunds", "settlements"}
    return httpx.Response(200, json={"_embedded": {key: []}})


def test_standalone_payment_uses_paid_date_and_paginates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/payments":
            if request.url.params.get("from"):
                return httpx.Response(
                    200,
                    json={"_embedded": {"payments": [_payment(id="tr_second")]}},
                )
            return httpx.Response(
                200,
                json={
                    "_embedded": {"payments": [_payment()]},
                    "_links": {
                        "next": {"href": "https://api.mollie.com/v2/payments?from=tr_second"}
                    },
                },
            )
        return _empty_resource(request)

    _mock_client(monkeypatch, handler)
    rows = MollieClearingGateway("token").fetch(START, END)

    assert [row.provider_ref for row in rows] == ["tr_standalone", "tr_second"]
    assert all(row.kind == TransactionKind.PAYMENT for row in rows)
    assert all(row.created_at == datetime(2026, 9, 10, 14, tzinfo=VIENNA) for row in rows)
    assert all(row.amount == money("29.90") for row in rows)
    assert all(row.provider_reference_ids == ("wix_payment",) for row in rows)
    assert all(row.order_number == "" for row in rows)
    assert requests[0].url.params["limit"] == "250"


def test_order_linked_payments_use_individual_amounts_and_keep_order_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_reads: list[str] = []
    first = _payment(id="tr_first", orderId="ord_1", amount={"currency": "EUR", "value": "10.00"})
    second = _payment(
        id="tr_second",
        _links={"order": {"href": "https://api.mollie.com/v2/orders/ord_1"}},
        amount={"currency": "EUR", "value": "19.90"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/payments":
            return httpx.Response(200, json={"_embedded": {"payments": [first, second, first]}})
        if request.url.path == "/v2/orders/ord_1":
            order_reads.append(request.url.path)
            return httpx.Response(
                200,
                json={
                    "orderNumber": "12345",
                    "status": "completed",
                    "amount": {"currency": "EUR", "value": "29.90"},
                    "billingAddress": {"givenName": "Anna", "familyName": "Test", "email": "a@test.invalid"},
                },
            )
        return _empty_resource(request)

    _mock_client(monkeypatch, handler)
    rows = MollieClearingGateway("token").fetch(START, END)

    assert [row.provider_ref for row in rows] == ["tr_first", "tr_second"]
    assert [row.amount for row in rows] == [money("10.00"), money("19.90")]
    assert all(row.order_number == "12345" and row.provider_order_id == "ord_1" for row in rows)
    assert all(row.customer == "Anna Test" and row.email == "a@test.invalid" for row in rows)
    assert order_reads == ["/v2/orders/ord_1"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "open"},
        {"status": "pending"},
        {"status": "failed"},
        {"status": "expired"},
        {"status": "canceled"},
        {"paidAt": "2026-08-31T21:59:59Z"},
        {"paidAt": "2026-09-30T22:00:00Z"},
        {"amount": {"currency": "USD", "value": "29.90"}},
    ],
)
def test_ineligible_payments_are_excluded(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/payments":
            return httpx.Response(200, json={"_embedded": {"payments": [_payment(**overrides)]}})
        return _empty_resource(request)

    _mock_client(monkeypatch, handler)
    assert MollieClearingGateway("token").fetch(START, END) == []


@pytest.mark.parametrize(
    "overrides",
    [{"paidAt": None}, {"paidAt": "invalid"}, {"id": ""}, {"amount": {"currency": "EUR", "value": "0.00"}}],
)
def test_invalid_paid_payment_is_quarantined_with_warning(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/payments":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payments": [
                            _payment(**overrides),
                            _payment(id="tr_valid", metadata={}),
                        ]
                    }
                },
            )
        return _empty_resource(request)

    _mock_client(monkeypatch, handler)
    gateway = MollieClearingGateway("token")
    rows = gateway.fetch(START, END)

    assert [row.provider_ref for row in rows] == ["tr_valid"]
    assert "ausgelassen" in gateway.last_warning


def test_payments_permission_error_is_not_an_empty_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_client(monkeypatch, lambda request: httpx.Response(403, json={"detail": "Forbidden"}))
    with pytest.raises(httpx.HTTPStatusError):
        MollieClearingGateway("token").fetch(START, END)


def test_standalone_payment_reaches_clearing_and_preserves_existing_booking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/payments":
            return httpx.Response(200, json={"_embedded": {"payments": [_payment()]}})
        return _empty_resource(request)

    _mock_client(monkeypatch, handler)
    stripe = MagicMock()
    stripe.fetch.return_value = []
    stripe.last_warning = ""
    wix = MagicMock()
    wix.provider_map.return_value = ({"tr_standalone": "12345"}, {})
    sevdesk = MagicMock()
    sevdesk.account_ids.return_value = {"stripe": 11, "mollie": 12}
    sevdesk.invoices.return_value = [
        InvoiceRecord(7, "RE-100", "Wix | 12345", money("29.90"), 200, "Anna")
    ]
    sevdesk.transactions.return_value = []
    service = PaymentClearingService(
        stripe=stripe,
        mollie=MollieClearingGateway("token"),
        wix=wix,
        sevdesk=sevdesk,
        history_dir=tmp_path,
    )

    analysis = service.analyze(START.date(), datetime(2026, 9, 30).date())
    row = analysis.candidates[0]

    assert len(analysis.candidates) == 1
    assert row.provider == "mollie"
    assert row.status == MatchStatus.READY
    assert row.order_number == "12345"
    assert row.invoice_id == 7
    assert row.stable_key == "payment|mollie|tr_standalone|2026-09-10|29.90"
    sevdesk.create_transaction.assert_not_called()
    sevdesk.book_invoice.assert_not_called()

    sevdesk.invoices.return_value = [
        InvoiceRecord(7, "RE-100", "Wix | 12345", money("29.90"), 1000, "Anna")
    ]
    already_paid = service.analyze(START.date(), datetime(2026, 9, 30).date()).candidates[0]
    assert already_paid.status == MatchStatus.ALREADY_BOOKED
    assert not already_paid.selected

    sevdesk.invoices.return_value = [
        InvoiceRecord(7, "RE-100", "Wix | 12345", money("29.90"), 200, "Anna")
    ]
    existing = SevdeskTransaction(
        99, 12, money("29.90"), row.payment_date, "mollie:tr_standalone | PAYMENT", 400
    )
    sevdesk.transactions.side_effect = (
        lambda account_id, start, end: [existing] if account_id == 12 else []
    )
    already_booked = service.analyze(START.date(), datetime(2026, 9, 30).date()).candidates[0]
    assert already_booked.status == MatchStatus.ALREADY_BOOKED
    assert already_booked.transaction_id == 99
    assert not already_booked.selected
