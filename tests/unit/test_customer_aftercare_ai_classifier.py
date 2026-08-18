"""Tests for Lieferkorrektur AI classification (spec §3) — always advisory, never blocking."""
from __future__ import annotations

import httpx
import pytest

from xw_office.services.customer_aftercare.ai_classifier import classify_mail


def test_classify_mail_without_api_key_uses_fallback() -> None:
    result = classify_mail(
        subject="Falsche Lieferung",
        sender="Haendler Mueller <mueller@example.com>",
        body_text="Wir haben Artikel A statt B erhalten.",
        api_key=None,
    )
    assert result.source == "fallback"
    assert result.case_type == "UNKNOWN"
    assert result.confidence == 0.0
    assert result.customer_email == "mueller@example.com"


def test_classify_mail_falls_back_when_openai_call_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingClient:
        def __enter__(self) -> "_FailingClient":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            raise httpx.ConnectError("boom", request=httpx.Request("POST", url))

    monkeypatch.setattr(
        "xw_office.services.customer_aftercare.ai_classifier.httpx.Client",
        lambda timeout: _FailingClient(),
    )

    result = classify_mail(
        subject="Falsche Lieferung",
        sender="mueller@example.com",
        body_text="Wir haben Artikel A statt B erhalten.",
        api_key="sk-test",
    )
    assert result.source == "fallback"
    assert result.case_type == "UNKNOWN"


def test_classify_mail_parses_openai_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyClient:
        def __enter__(self) -> "_DummyClient":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            request = httpx.Request("POST", url, json=json, headers=headers)
            return httpx.Response(
                200,
                request=request,
                json={
                    "output_text": (
                        '{"case_type": "B2B_WRONG_DELIVERY", "confidence": 0.9, '
                        '"customer_name": "Musikhaus Mueller", '
                        '"customer_email": "mueller@example.com", '
                        '"wix_order_number": "21842", "error_party": "xeisworks", '
                        '"wrong_items": [{"name": "Notenheft A", "sku": "XW-1", "quantity": "2"}], '
                        '"missing_items": [{"name": "Notenheft B", "sku": "XW-2", "quantity": "1"}], '
                        '"courtesy_suggested": true, "note": "Falschlieferung erkannt"}'
                    )
                },
            )

    monkeypatch.setattr(
        "xw_office.services.customer_aftercare.ai_classifier.httpx.Client",
        lambda timeout: _DummyClient(),
    )

    result = classify_mail(
        subject="Falsche Lieferung zu Bestellung 21842",
        sender="mueller@example.com",
        body_text="Wir haben Notenheft A statt Notenheft B erhalten.",
        api_key="sk-test",
    )
    assert result.source == "openai"
    assert result.case_type == "B2B_WRONG_DELIVERY"
    assert result.confidence == 0.9
    assert result.wix_order_number == "21842"
    assert result.error_party == "xeisworks"
    assert [item.name for item in result.wrong_items] == ["Notenheft A"]
    assert [item.name for item in result.missing_items] == ["Notenheft B"]
    assert result.courtesy_suggested is True


def test_classify_mail_rejects_unknown_case_type_from_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyClient:
        def __enter__(self) -> "_DummyClient":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            request = httpx.Request("POST", url, json=json, headers=headers)
            return httpx.Response(
                200,
                request=request,
                json={"output_text": '{"case_type": "SOMETHING_MADE_UP", "confidence": 0.8}'},
            )

    monkeypatch.setattr(
        "xw_office.services.customer_aftercare.ai_classifier.httpx.Client",
        lambda timeout: _DummyClient(),
    )

    result = classify_mail(subject="?", sender="a@b.com", body_text="?", api_key="sk-test")
    assert result.source == "openai"
    assert result.case_type == "UNKNOWN"


def test_to_payload_json_round_trips_for_audit_trail() -> None:
    result = classify_mail(
        subject="s", sender="a@b.com", body_text="b", api_key=None
    )
    import json

    payload = json.loads(result.to_payload_json())
    assert payload["case_type"] == "UNKNOWN"
    assert payload["source"] == "fallback"
