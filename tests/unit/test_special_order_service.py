from __future__ import annotations

import json
from threading import Lock

import httpx
import pytest

from xw_office.services.special_orders.service import SpecialOrderItem, SpecialOrderLink, SpecialOrderService


class _SharedSettings:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lock = Lock()

    def mutate_value_json(self, key: str, mutator: object) -> str:
        with self.lock:
            updated = mutator(self.values.get(key))  # type: ignore[operator]
            self.values[key] = updated
            return updated

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)


class _Secrets:
    def get_secret(self, name: str) -> str:
        return {"XW_SPECIAL_ORDER_ENDPOINT": "https://example.test/link", "XW_SPECIAL_ORDER_SECRET": "secret"}.get(name, "")


def _service(settings: _SharedSettings) -> SpecialOrderService:
    return SpecialOrderService(secret_service=_Secrets(), wix_products=object(), settings_repo=settings)  # type: ignore[arg-type]


def _create(service: SpecialOrderService) -> SpecialOrderLink:
    return service.create_payment_link(
        mode="digital_custom",
        title="Testauftrag",
        description="",
        items=[SpecialOrderItem(name="Test", price="12.00")],
        customer_email="",
        customer_first_name="",
        customer_last_name="",
    )


def test_endpoint_response_without_json_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="keine JSON-Antwort"):
        SpecialOrderService._link_from_endpoint_response(None, fallback_title="Test")


def test_endpoint_response_without_success_reports_server_error() -> None:
    with pytest.raises(RuntimeError, match="Payment Link fehlgeschlagen"):
        SpecialOrderService._link_from_endpoint_response(
            {"ok": False, "message": "Payment Link fehlgeschlagen"},
            fallback_title="Test",
        )


def test_endpoint_response_does_not_accept_string_false_as_success() -> None:
    with pytest.raises(RuntimeError, match="Payment Link fehlgeschlagen"):
        SpecialOrderService._link_from_endpoint_response(
            {"ok": "false", "url": "https://example.test/pay"},
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

    nested_url = SpecialOrderService._link_from_rest_response(
        {
            "paymentLink": {
                "id": "link-2",
                "links": {"url": {"url": "https://example.test/nested-pay"}},
            }
        },
        fallback_title="Fallback",
    )
    assert nested_url.url == "https://example.test/nested-pay"

    with pytest.raises(RuntimeError, match="keinen Payment-Link-URL"):
        SpecialOrderService._link_from_rest_response(
            {"paymentLink": None}, fallback_title="Fallback"
        )


def test_unclear_payment_link_result_blocks_retry_across_service_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _SharedSettings()
    first = _service(settings)
    second = _service(settings)
    sent_keys: list[str] = []

    def accepted_then_timed_out(payload: dict[str, object], *, fallback_title: str) -> SpecialOrderLink:
        sent_keys.append(str(payload["clientRequestKey"]))
        raise TimeoutError("response lost")

    monkeypatch.setattr(first, "_create_payment_link_via_endpoint", accepted_then_timed_out)
    monkeypatch.setattr(second, "_create_payment_link_via_endpoint", accepted_then_timed_out)
    monkeypatch.setattr(second, "_readback_payment_links_by_request_key", lambda _key: [])
    with pytest.raises(TimeoutError):
        _create(first)
    with pytest.raises(RuntimeError, match="Ergebnis ist noch offen oder unklar"):
        _create(second)
    assert len(sent_keys) == 1
    assert json.loads(next(iter(settings.values.values())))["state"] == "unknown"


def test_endpoint_readback_reconciles_unclear_claim_without_duplicate_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _SharedSettings()
    first = _service(settings)
    second = _service(settings)
    sent_keys: list[str] = []
    readback_requests: list[dict[str, object]] = []

    def accepted_then_timed_out(payload: dict[str, object], *, fallback_title: str) -> SpecialOrderLink:
        sent_keys.append(str(payload["clientRequestKey"]))
        raise TimeoutError("response lost")

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 30.0

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            readback_requests.append({"url": url, "headers": headers, "json": json})
            return httpx.Response(200, json={
                "ok": True,
                "matches": [{
                    "id": "endpoint-link",
                    "url": "https://example.test/recovered",
                    "status": "ACTIVE",
                    "title": "Testauftrag",
                }],
            })

    monkeypatch.setattr(first, "_create_payment_link_via_endpoint", accepted_then_timed_out)
    monkeypatch.setattr("xw_office.services.special_orders.service.httpx.Client", _Client)
    with pytest.raises(TimeoutError):
        _create(first)

    recovered = _create(second)

    assert recovered.id == "endpoint-link"
    assert recovered.url == "https://example.test/recovered"
    assert readback_requests[0]["json"] == {
        "action": "readback",
        "clientRequestKey": sent_keys[0],
    }
    assert readback_requests[0]["headers"]["x-xw-special-order-secret"] == "secret"  # type: ignore[index]
    claim = json.loads(next(iter(settings.values.values())))
    assert claim["state"] == "succeeded"
    assert len(sent_keys) == 1


@pytest.mark.parametrize("readback_result", [
    {"ok": True, "matches": []},
    {"ok": True, "matches": [{"id": "one", "url": "https://example.test/one"}] * 2},
    {"ok": True, "matches": [{"id": "missing-url"}]},
    {"ok": False, "error": "wix_search_failed"},
    {"ok": True, "matches": "invalid"},
])
def test_endpoint_readback_without_one_valid_match_keeps_claim_unknown(
    monkeypatch: pytest.MonkeyPatch,
    readback_result: dict[str, object],
) -> None:
    settings = _SharedSettings()
    first = _service(settings)
    second = _service(settings)
    sent_keys: list[str] = []
    readback_count = 0

    def accepted_then_timed_out(payload: dict[str, object], *, fallback_title: str) -> SpecialOrderLink:
        sent_keys.append(str(payload["clientRequestKey"]))
        raise TimeoutError("response lost")

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, _url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            nonlocal readback_count
            readback_count += 1
            return httpx.Response(200, json=readback_result)

    monkeypatch.setattr(first, "_create_payment_link_via_endpoint", accepted_then_timed_out)
    monkeypatch.setattr("xw_office.services.special_orders.service.httpx.Client", _Client)
    with pytest.raises(TimeoutError):
        _create(first)
    with pytest.raises(RuntimeError, match="Ergebnis ist noch offen oder unklar"):
        _create(second)

    claim = json.loads(next(iter(settings.values.values())))
    assert claim["state"] == "unknown"
    assert len(sent_keys) == 1
    assert readback_count == 1


def test_exact_wix_readback_reconciles_unclear_claim_without_second_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _SharedSettings()
    first = _service(settings)
    second = _service(settings)
    sent_keys: list[str] = []

    def accepted_then_timed_out(payload: dict[str, object], *, fallback_title: str) -> SpecialOrderLink:
        sent_keys.append(str(payload["clientRequestKey"]))
        raise TimeoutError("response lost")

    recovered = SpecialOrderLink(
        id="wix-link-1",
        url="https://example.test/pay-existing",
        status="ACTIVE",
        title="Testauftrag",
    )
    monkeypatch.setattr(first, "_create_payment_link_via_endpoint", accepted_then_timed_out)
    monkeypatch.setattr(second, "_wix_api_key", lambda: "test-key")
    monkeypatch.setattr(second, "_wix_site_id", lambda: "test-site")
    monkeypatch.setattr(
        second,
        "search_payment_links_by_request_key",
        lambda request_key: [recovered] if request_key == sent_keys[0] else [],
    )

    with pytest.raises(TimeoutError):
        _create(first)
    assert _create(second) == recovered
    claim = json.loads(next(iter(settings.values.values())))
    assert claim["state"] == "succeeded"
    assert claim["reconciliation_history"]
    assert len(sent_keys) == 1


def test_ambiguous_wix_readback_keeps_claim_unknown_and_blocks_second_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _SharedSettings()
    first = _service(settings)
    second = _service(settings)
    sent_keys: list[str] = []

    def accepted_then_timed_out(payload: dict[str, object], *, fallback_title: str) -> SpecialOrderLink:
        sent_keys.append(str(payload["clientRequestKey"]))
        raise TimeoutError("response lost")

    possible = SpecialOrderLink(
        id="possible-link",
        url="https://example.test/possible",
        status="ACTIVE",
        title="Testauftrag",
    )
    monkeypatch.setattr(first, "_create_payment_link_via_endpoint", accepted_then_timed_out)
    monkeypatch.setattr(second, "_wix_api_key", lambda: "test-key")
    monkeypatch.setattr(second, "_wix_site_id", lambda: "test-site")
    monkeypatch.setattr(second, "search_payment_links_by_request_key", lambda _key: [possible, possible])

    with pytest.raises(TimeoutError):
        _create(first)
    with pytest.raises(RuntimeError, match="Ergebnis ist noch offen oder unklar"):
        _create(second)

    claim = json.loads(next(iter(settings.values.values())))
    assert claim["state"] == "unknown"
    assert len(sent_keys) == 1


def test_wix_readback_accepts_only_exact_note_request_key(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(_SharedSettings())
    monkeypatch.setattr(service, "_wix_api_key", lambda: "test-key")
    monkeypatch.setattr(service, "_wix_site_id", lambda: "test-site")
    request: dict[str, object] = {}
    key = "request-123"

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 30.0

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            request.update(url=url, headers=headers, json=json)
            return httpx.Response(
                200,
                json={
                    "paymentLinks": [
                        {
                            "id": "link-exact",
                            "title": "Found",
                            "note": {"text": '{"clientRequestKey":"request-123"}'},
                            "links": {"url": {"url": "https://example.test/exact"}},
                        },
                        {
                            "id": "link-fuzzy-only",
                            "title": "Other",
                            "note": {"text": '{"clientRequestKey":"request-1234"}'},
                            "links": {"url": {"url": "https://example.test/other"}},
                        },
                    ]
                },
            )

    monkeypatch.setattr("xw_office.services.special_orders.service.httpx.Client", _Client)

    matches = service.search_payment_links_by_request_key(key)

    assert [(link.id, link.url) for link in matches] == [
        ("link-exact", "https://example.test/exact")
    ]
    assert request["url"] == "https://www.wixapis.com/payment-links/v1/payment-links/search"
    body = request["json"]
    assert isinstance(body, dict)
    search = body["search"]
    assert isinstance(search, dict)
    assert search["search"] == {
        "expression": key,
        "fields": ["note.text"],
        "fuzzy": False,
    }


def test_confirmed_link_allows_deliberate_new_run_with_new_request_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _SharedSettings()
    service = _service(settings)
    sent_keys: list[str] = []

    def success(payload: dict[str, object], *, fallback_title: str) -> SpecialOrderLink:
        sent_keys.append(str(payload["clientRequestKey"]))
        return SpecialOrderLink(id="link", url="https://example.test/pay", status="ACTIVE", title=fallback_title)

    monkeypatch.setattr(service, "_create_payment_link_via_endpoint", success)
    _create(service)
    _create(service)
    assert len(sent_keys) == 2
    assert sent_keys[0] != sent_keys[1]
