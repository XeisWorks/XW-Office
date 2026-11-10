from __future__ import annotations

import json
from threading import Lock

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
    with pytest.raises(TimeoutError):
        _create(first)
    with pytest.raises(RuntimeError, match="Ergebnis ist noch offen oder unklar"):
        _create(second)
    assert len(sent_keys) == 1
    assert json.loads(next(iter(settings.values.values())))["state"] == "unknown"


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
