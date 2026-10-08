"""Tests for HTTP helpers."""
import gzip
import httpx
import pytest

from xw_office.core.config import AppConfig
from xw_office.core.exceptions import SevdeskApiError
from xw_office.services.http_client import (
    SevdeskConnection,
    SevdeskRateLimiter,
    build_sevdesk_connection,
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


def test_built_connection_paces_requests_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    now = {"value": 100.0}
    sleeps: list[float] = []

    monkeypatch.setattr("xw_office.services.http_client.time.monotonic", lambda: now["value"])

    def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        now["value"] += delay

    monkeypatch.setattr("xw_office.services.http_client.time.sleep", fake_sleep)
    connection = build_sevdesk_connection(AppConfig())
    assert connection.rate_limiter is not None

    connection.rate_limiter.acquire()
    connection.rate_limiter.acquire()

    assert sum(sleeps) == pytest.approx(0.5)


def test_rate_limiter_applies_retry_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    now = {"value": 200.0}
    sleeps: list[float] = []

    monkeypatch.setattr("xw_office.services.http_client.time.monotonic", lambda: now["value"])

    def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        now["value"] += delay

    monkeypatch.setattr("xw_office.services.http_client.time.sleep", fake_sleep)
    limiter = SevdeskRateLimiter(requests_per_second=2, cooldown_seconds=5)
    limiter.acquire()
    limiter.observe(httpx.Response(429, headers={"Retry-After": "3"}))
    limiter.acquire()

    assert sum(sleeps) == pytest.approx(3.0)


def test_read_session_reuses_only_identical_queries_and_discards_on_exit() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"objects": [{"version": len(calls)}]})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        connection = SevdeskConnection(client, AppConfig())
        with connection.read_session() as session:
            first = connection.get("/InvoicePos", params={"id": "1", "embed": "part"})
            reused = connection.get("/InvoicePos", params={"embed": "part", "id": "1"})
            assert reused is not first
            assert reused.json() == first.json()
            connection.get("/InvoicePos", params={"id": "2", "embed": "part"})
            assert (session.requests, session.cache_hits) == (2, 1)
        assert session.responses == {}
        with connection.read_session():
            refreshed = connection.get("/InvoicePos", params={"id": "1", "embed": "part"})
        assert refreshed.json() != first.json()
        connection.get("/InvoicePos", params={"id": "1", "embed": "part"})
    assert len(calls) == 4


def test_read_session_does_not_cache_failures_and_cleans_up_after_exception() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401 if calls == 1 else 200, json={"objects": []})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        connection = SevdeskConnection(client, AppConfig())
        with pytest.raises(RuntimeError, match="stop"):
            with connection.read_session() as session:
                with pytest.raises(SevdeskApiError):
                    connection.get("/Invoice")
                connection.get("/Invoice")
                assert session.requests == 2
                assert session.cache_hits == 0
                raise RuntimeError("stop")
        assert session.responses == {}
        connection.get("/Invoice")
    assert calls == 3


def test_read_session_is_not_shared_with_other_workers() -> None:
    from concurrent.futures import ThreadPoolExecutor

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"objects": []})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        connection = SevdeskConnection(client, AppConfig())
        with connection.read_session() as session:
            connection.get("/Invoice")
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(connection.get, "/Invoice").result()
            assert session.requests == 1
            assert session.cache_hits == 0
            connection.get("/Invoice")
            assert session.cache_hits == 1


def test_read_session_reuses_already_decoded_compressed_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=gzip.compress(b'{"objects":[{"id":"1"}]}'),
            headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        connection = SevdeskConnection(client, AppConfig())
        with connection.read_session() as session:
            first = connection.get("/InvoicePos")
            reused = connection.get("/InvoicePos")
            assert first.json() == reused.json() == {"objects": [{"id": "1"}]}
            assert "content-encoding" not in reused.headers
            assert int(reused.headers["content-length"]) == len(reused.content)
            assert session.cache_hits == 1
