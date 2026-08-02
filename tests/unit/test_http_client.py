"""Tests for HTTP helpers."""
import httpx
import pytest

from xw_office.core.config import AppConfig
from xw_office.core.exceptions import SevdeskApiError
from xw_office.services.http_client import (
    humanize_sevdesk_error,
    raise_for_sevdesk,
    sevdesk_get_with_retry,
)


def test_humanize_401_contains_token_hint() -> None:
    msg = humanize_sevdesk_error(401, "")
    assert "401" in msg or "Token" in msg


def test_raise_for_sevdesk_success() -> None:
    response = httpx.Response(200, json={"ok": True})
    raise_for_sevdesk(response)


def test_raise_for_sevdesk_raises_on_error() -> None:
    response = httpx.Response(401, text="unauthorized")
    with pytest.raises(SevdeskApiError) as excinfo:
        raise_for_sevdesk(response)
    assert excinfo.value.status_code == 401


def test_sevdesk_get_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "xw_office.services.http_client.time.sleep",
        lambda _s: None,
    )

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"objects": []})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    cfg = AppConfig()
    response = sevdesk_get_with_retry(client, cfg, "/Invoice", params={})
    assert response.status_code == 200
    assert attempts["n"] == 2
