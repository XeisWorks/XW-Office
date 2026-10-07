from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx
import pytest

from xw_office.core.config import AppConfig
from xw_office.services.clearing.gateways import (
    MollieClearingGateway,
    SevdeskClearingGateway,
    StripeClearingGateway,
    WixClearingGateway,
)
from xw_office.services.clearing.mollie_cache import MolliePaymentCache
from xw_office.services.http_client import SevdeskConnection

VIENNA = ZoneInfo("Europe/Vienna")
START = datetime(2026, 9, 1, tzinfo=VIENNA)
END = datetime(2026, 10, 1, tzinfo=VIENNA)


class _MemorySettingsRepository:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def mutate_value_json(self, key: str, mutator: Callable[[str | None], str]) -> str:
        value = mutator(self.values.get(key))
        self.values[key] = value
        return value


def _mock_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    original_client = httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return original_client(*args, **kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", factory)


def _payment(
    payment_id: str,
    status: str,
    created_at: str,
    *,
    paid_at: str = "",
    amount: str = "29.90",
) -> dict[str, Any]:
    return {
        "id": payment_id,
        "status": status,
        "createdAt": created_at,
        "paidAt": paid_at,
        "amount": {"currency": "EUR", "value": amount},
        "metadata": {"wix_transaction_id": "wix-ref"},
    }


def _empty_mollie(request: httpx.Request) -> httpx.Response:
    key = request.url.path.rsplit("/", 1)[-1]
    assert key in {"refunds", "settlements"}
    return httpx.Response(200, json={"_embedded": {key: []}})


def test_mollie_incrementally_refreshes_unresolved_and_keeps_old_payments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _MemorySettingsRepository()
    open_paid = False
    payment_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal open_paid
        path = request.url.path
        if path == "/v2/payments":
            payment_requests.append(str(request.url.params.get("from") or "first"))
            cursor = request.url.params.get("from")
            if cursor == "mid":
                rows = [_payment("tr_mid", "open", "2026-08-30T12:00:00Z")]
                return httpx.Response(
                    200,
                    json={
                        "_embedded": {"payments": rows},
                        "_links": {
                            "next": {"href": "https://api.mollie.com/v2/payments?from=tail"}
                        },
                    },
                )
            if cursor == "tail":
                return httpx.Response(
                    200,
                    json={"_embedded": {"payments": [_payment("tr_tail", "paid", "2026-08-29T12:00:00Z", paid_at="2026-09-09T12:00:00Z")]}},
                )
            if cursor == "head":
                return httpx.Response(
                    200,
                    json={"_embedded": {"payments": [_payment("tr_head", "paid", "2026-08-31T12:00:00Z", paid_at="2026-09-10T12:00:00Z")]}},
                )
            if payment_requests.count("first") == 1:
                return httpx.Response(
                    200,
                    json={
                        "_embedded": {
                            "payments": [
                                _payment("tr_head", "paid", "2026-08-31T12:00:00Z", paid_at="2026-09-10T12:00:00Z"),
                            ]
                        },
                        "_links": {
                            "next": {"href": "https://api.mollie.com/v2/payments?from=mid"}
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payments": [
                            _payment("tr_new", "paid", "2026-09-01T12:00:00Z", paid_at="2026-09-11T12:00:00Z"),
                        ]
                    },
                    "_links": {
                        "next": {"href": "https://api.mollie.com/v2/payments?from=head"}
                    },
                },
            )
        if path == "/v2/payments/tr_mid":
            status = "paid" if open_paid else "open"
            return httpx.Response(
                200,
                json=_payment(
                    "tr_mid",
                    status,
                    "2026-08-30T12:00:00Z",
                    paid_at="2026-09-12T12:00:00Z" if open_paid else "",
                ),
            )
        return _empty_mollie(request)

    _mock_client(monkeypatch, handler)
    gateway = MollieClearingGateway("token-A", settings_repo=repository)

    first_rows = gateway.fetch(START, END)
    assert {row.provider_ref for row in first_rows} == {"tr_head", "tr_tail"}
    first_request_count = len(payment_requests)
    assert first_request_count == 3

    open_paid = True
    second_rows = gateway.fetch(START, END)
    assert {row.provider_ref for row in second_rows} == {
        "tr_head",
        "tr_mid",
        "tr_tail",
        "tr_new",
    }
    assert len(payment_requests) - first_request_count == 2
    assert payment_requests[-2:] == ["first", "head"]

    cache_json = next(iter(repository.values.values()))
    assert '"billingAddress"' not in cache_json
    assert '"metadata"' not in cache_json
    assert '"wixReference":"wix-ref"' in cache_json


def test_mollie_warm_run_uses_listed_page_for_unresolved_and_keeps_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _MemorySettingsRepository()
    run = 1
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requests.append(path)
        if path == "/v2/payments":
            fresh = (
                _payment("tr_fresh", "paid", "2026-09-20T12:00:00Z", paid_at="2026-09-21T12:00:00Z")
                if run == 2
                else _payment("tr_fresh", "open", "2026-09-20T12:00:00Z")
            )
            enriched = _payment(
                "tr_enriched", "paid", "2026-09-02T12:00:00Z", paid_at="2026-09-03T12:00:00Z"
            )
            enriched["orderId"] = "ord_1"
            return httpx.Response(200, json={"_embedded": {"payments": [fresh, enriched]}})
        if path == "/v2/orders/ord_1":
            return httpx.Response(
                200,
                json={
                    "orderNumber": "10001",
                    "billingAddress": {"givenName": "A", "familyName": "B", "email": "a@b.c"},
                },
            )
        if path == "/v2/payments/tr_fresh":
            raise AssertionError("listed unresolved payment must not be fetched twice")
        return _empty_mollie(request)

    _mock_client(monkeypatch, handler)
    gateway = MollieClearingGateway("token-A", settings_repo=repository)
    first = gateway.fetch(START, END)
    assert {row.provider_ref for row in first} == {"tr_enriched"}
    assert requests.count("/v2/orders/ord_1") == 1

    run = 2
    requests.clear()
    second = gateway.fetch(START, END)
    assert {row.provider_ref for row in second} == {"tr_enriched", "tr_fresh"}
    assert requests == ["/v2/payments", "/v2/refunds", "/v2/settlements"]
    enriched_row = next(row for row in second if row.provider_ref == "tr_enriched")
    assert enriched_row.order_number == "10001"
    state = json.loads(next(iter(repository.values.values())))
    assert state["payments"]["tr_fresh"]["status"] == "paid"
    assert state["payments"]["tr_enriched"]["email"] == "a@b.c"

def test_mollie_cache_isolated_by_credential_and_periodic_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _MemorySettingsRepository()
    amount = "10.00"
    list_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal list_calls
        if request.url.path == "/v2/payments":
            list_calls += 1
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payments": [
                            _payment(
                                "tr_terminal",
                                "paid",
                                "2026-09-10T12:00:00Z",
                                paid_at="2026-09-10T12:00:00Z",
                                amount=amount,
                            )
                        ]
                    }
                },
            )
        return _empty_mollie(request)

    _mock_client(monkeypatch, handler)
    MollieClearingGateway("token-A", settings_repo=repository).fetch(START, END)
    assert len(repository.values) == 1

    cache = MolliePaymentCache(repository, "token-A")
    state = cache.read()
    assert state is not None
    state["full_refresh_at"] = 1
    repository.values[cache.key] = json.dumps(state)
    amount = "11.00"
    refreshed = MollieClearingGateway("token-A", settings_repo=repository).fetch(START, END)
    assert refreshed[0].amount == 11

    MollieClearingGateway("token-B", settings_repo=repository).fetch(START, END)
    assert len(repository.values) == 2
    assert list_calls == 3


def test_mollie_atomic_cache_merge_keeps_newer_payment_snapshot() -> None:
    repository = _MemorySettingsRepository()
    cache = MolliePaymentCache(repository, "token")
    cache.merge({"tr_1": {"status": "paid", "fetched_at": 20}})
    state = cache.merge({"tr_1": {"status": "open", "fetched_at": 10}})

    assert state["payments"]["tr_1"]["status"] == "paid"


def test_wix_blocks_conflicting_ids_and_reads_paging_metadata_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal search_calls
        if request.url.path.endswith("/orders/search"):
            search_calls += 1
            if search_calls == 1:
                return httpx.Response(
                    200,
                    json={
                        "orders": [{"id": "order-a", "number": "1001"}],
                        "pagingMetadata": {"nextCursor": "page-2"},
                    },
                )
            assert json.loads(request.content)["search"]["cursorPaging"]["cursor"] == "page-2"
            return httpx.Response(
                200,
                json={"orders": [{"id": "order-b", "number": "1002"}]},
            )
        if request.url.path.endswith("/payments/list-by-ids"):
            return httpx.Response(
                200,
                json={
                    "orderTransactions": [
                        {
                            "orderId": "order-a",
                            "payments": [{"regularPaymentDetails": {"providerTransactionId": "same-id"}}],
                        },
                        {
                            "orderId": "order-b",
                            "payments": [{"regularPaymentDetails": {"providerTransactionId": "same-id"}}],
                        },
                    ]
                },
            )
        raise AssertionError(request.url)

    _mock_client(monkeypatch, handler)
    gateway = WixClearingGateway("api", "site")
    provider_map, _ = gateway.provider_map(START, END)

    assert search_calls == 2
    assert "same-id" not in provider_map
    assert "same-id" in gateway.blocked_reference_ids
    assert "same-id" in gateway.last_warning


def test_wix_batch_fallback_failures_and_missing_orders_are_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/orders/search"):
            return httpx.Response(
                200,
                json={"orders": [{"id": "order-a", "number": "1001"}, {"id": "order-b", "number": "1002"}]},
            )
        if request.url.path.endswith("/payments/list-by-ids"):
            return httpx.Response(503)
        if request.url.path.endswith("/payments/orders/order-a"):
            return httpx.Response(
                200,
                json={
                    "orderTransactions": {
                        "orderId": "order-a",
                        "payments": [{"regularPaymentDetails": {"providerTransactionId": "provider-a"}}],
                    }
                },
            )
        if request.url.path.endswith("/payments/orders/order-b"):
            return httpx.Response(404)
        raise AssertionError(request.url)

    _mock_client(monkeypatch, handler)
    gateway = WixClearingGateway("api", "site")
    provider_map, _ = gateway.provider_map(START, END)

    assert provider_map["provider-a"] == "1001"
    assert gateway.lookup_complete is True
    assert "503" in gateway.last_warning
    assert "404" in gateway.last_warning
    assert "no transactions" in gateway.last_warning


@pytest.mark.parametrize("failure", ["batch_omits_order", "single_server_error", "single_invalid"])
def test_wix_incomplete_payment_lookup_blocks_unverified_payment_references(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    payment_a = {
        "orderId": "order-a",
        "payments": [{"regularPaymentDetails": {"providerTransactionId": "provider-a"}}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/orders/search"):
            return httpx.Response(
                200,
                json={"orders": [{"id": "order-a", "number": "1001"}, {"id": "order-b", "number": "1002"}]},
            )
        if path.endswith("/payments/list-by-ids"):
            if failure == "batch_omits_order":
                return httpx.Response(200, json={"orderTransactions": [payment_a]})
            return httpx.Response(503)
        if path.endswith("/payments/orders/order-a"):
            return httpx.Response(200, json={"orderTransactions": payment_a})
        if path.endswith("/payments/orders/order-b"):
            if failure == "single_server_error":
                return httpx.Response(500)
            return httpx.Response(200, json={"orderTransactions": "broken"})
        raise AssertionError(request.url)

    _mock_client(monkeypatch, handler)
    gateway = WixClearingGateway("api", "site")
    provider_map, _ = gateway.provider_map(START, END)

    assert gateway.lookup_complete is False
    assert gateway.incomplete_order_ids == {"order-b"}
    assert "provider-a" not in provider_map
    assert "provider-a" in gateway.blocked_reference_ids
    assert provider_map["order-a"] == "1001"
    assert "incomplete" in gateway.last_warning


def test_wix_order_search_rejects_invalid_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"orders": "broken"}))
    with pytest.raises(ValueError):
        WixClearingGateway("api", "site").provider_map(START, END)


def test_wix_order_search_rejects_repeated_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(
        monkeypatch,
        lambda request: httpx.Response(200, json={"orders": [], "metadata": {"cursors": {"next": "c1"}}}),
    )
    with pytest.raises(RuntimeError):
        WixClearingGateway("api", "site").provider_map(START, END)


def test_wix_direct_resolver_raises_for_non_not_found_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_client(monkeypatch, lambda request: httpx.Response(503, request=request))

    with pytest.raises(httpx.HTTPStatusError):
        WixClearingGateway("api", "site").resolve_order_number("order-a")


def test_stripe_historical_refund_uses_expanded_intent_and_charge_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/charges"):
            return httpx.Response(200, json={"data": [], "has_more": False})
        if request.url.path.endswith("/refunds"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "re_old",
                            "currency": "eur",
                            "status": "succeeded",
                            "created": int(datetime(2026, 9, 10, tzinfo=VIENNA).timestamp()),
                            "amount": 990,
                            "charge": {
                                "id": "ch_historical",
                                "payment_intent": {"id": "pi_historical"},
                            },
                        }
                    ],
                    "has_more": False,
                },
            )
        return httpx.Response(200, json={"data": [], "has_more": False})

    _mock_client(monkeypatch, handler)
    rows = StripeClearingGateway("sk_test").fetch(START, END)

    refund = next(row for row in rows if row.provider_ref == "re_old")
    assert refund.provider_order_id == "pi_historical"
    assert "ch_historical" in refund.provider_reference_ids
    charge_request = next(request for request in requests if request.url.path.endswith("/charges"))
    refund_request = next(request for request in requests if request.url.path.endswith("/refunds"))
    assert "expand%5B%5D" not in str(charge_request.url)
    assert refund_request.url.params["expand[]"] == "data.charge.payment_intent"


def test_sevdesk_version_lookup_failure_does_not_assume_old_version() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        ),
        base_url="https://example.test/api/v1",
    )
    gateway = SevdeskClearingGateway(
        SevdeskConnection(client=client, config=AppConfig())
    )

    with pytest.raises(Exception):
        gateway._bookkeeping_system_version()


def test_sevdesk_link_invoice_only_falls_back_after_method_unsupported() -> None:
    class Connection:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.calls: list[str] = []

        def put(self, endpoint: str, **kwargs: Any) -> httpx.Response:
            self.calls.append("put")
            assert endpoint.endswith("/linkInvoice")
            assert kwargs["params"]["invoiceId"]
            if self.status_code in {405, 501}:
                raise httpx.HTTPStatusError(
                    "unsupported",
                    request=httpx.Request("PUT", "https://example.test"),
                    response=httpx.Response(
                        self.status_code,
                        request=httpx.Request("PUT", "https://example.test"),
                    ),
                )
            raise httpx.HTTPStatusError(
                "request failed",
                request=httpx.Request("PUT", "https://example.test"),
                response=httpx.Response(
                    self.status_code,
                    request=httpx.Request("PUT", "https://example.test"),
                ),
            )

        def patch(self, endpoint: str, **kwargs: Any) -> httpx.Response:
            self.calls.append("patch")
            assert endpoint.endswith("/linkInvoice")
            assert kwargs["params"]["invoiceId"]
            return httpx.Response(200, json={"objects": {"id": 1}})

    unsupported_connection = Connection(405)
    unsupported_gateway = SevdeskClearingGateway(unsupported_connection)  # type: ignore[arg-type]
    unsupported_gateway._legacy_link_invoice(
        transaction_id=1,
        invoice_id=2,
        amount=Decimal("10.00"),
        booking_date=1,
    )
    assert unsupported_connection.calls == ["put", "patch"]

    failed_connection = Connection(503)
    failed_gateway = SevdeskClearingGateway(failed_connection)  # type: ignore[arg-type]
    with pytest.raises(httpx.HTTPStatusError):
        failed_gateway._legacy_link_invoice(
            transaction_id=1,
            invoice_id=2,
            amount=Decimal("10.00"),
            booking_date=1,
        )
    assert failed_connection.calls == ["put"]


def test_sevdesk_booking_rejects_draft_and_amount_mismatch_before_writes() -> None:
    class Connection:
        def put(self, endpoint: str, **kwargs: Any) -> httpx.Response:
            raise AssertionError(f"unexpected write to {endpoint}: {kwargs}")

    gateway = SevdeskClearingGateway(Connection())  # type: ignore[arg-type]
    gateway.get_invoice_by_id = lambda _: {"status": 100}  # type: ignore[method-assign]
    draft = gateway.book_invoice(
        invoice_id=1,
        amount=Decimal("10.00"),
        payment_date=START,
        account_id=11,
        transaction_id=2,
    )
    assert draft["status"] == "invoice_draft"

    gateway.get_invoice_by_id = lambda _: {"status": 200}  # type: ignore[method-assign]
    gateway.get_check_account_transaction_by_id = lambda _: {  # type: ignore[method-assign]
        "status": 100,
        "amount": "10.01",
        "checkAccount": {"id": 11},
    }
    mismatch = gateway.book_invoice(
        invoice_id=1,
        amount=Decimal("10.00"),
        payment_date=START,
        account_id=11,
        transaction_id=2,
    )
    assert mismatch["status"] == "transaction_amount_mismatch"


def test_sevdesk_preserves_paid_result_and_warns_if_status_adjustment_fails() -> None:
    class Connection:
        def put(self, endpoint: str, **kwargs: Any) -> httpx.Response:
            assert endpoint.endswith("/Invoice/1/bookAmount")
            assert kwargs["json"]["amount"] == 10.0
            return httpx.Response(200, json={"objects": {}})

    gateway = SevdeskClearingGateway(Connection())  # type: ignore[arg-type]
    gateway._bookkeeping_version = "2.0"
    invoice_reads = 0
    transaction_reads = 0

    def get_invoice(_: int) -> dict[str, Any]:
        nonlocal invoice_reads
        invoice_reads += 1
        return {"status": 200 if invoice_reads == 1 else 1000}

    def get_transaction(_: int) -> dict[str, Any]:
        nonlocal transaction_reads
        transaction_reads += 1
        return {"status": 100, "amount": "10.00", "checkAccount": {"id": 11}}

    def fail_status_update(_: int, _status: int) -> dict[str, Any]:
        assert _status == 400
        raise RuntimeError("write unavailable")

    gateway.get_invoice_by_id = get_invoice  # type: ignore[method-assign]
    gateway.get_check_account_transaction_by_id = get_transaction  # type: ignore[method-assign]
    gateway.change_check_account_transaction_status = fail_status_update  # type: ignore[method-assign]
    result = gateway.book_invoice(
        invoice_id=1,
        amount=Decimal("10.00"),
        payment_date=START,
        account_id=11,
        transaction_id=2,
    )

    assert result["status"] == "booked"
    assert "warning" in result
