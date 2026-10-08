"""Shared httpx factory and helpers for external REST APIs."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol

import httpx

from xw_office.core.config import AppConfig
from xw_office.core.exceptions import SevdeskApiError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class CancellationToken(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


class SevdeskRateLimiter:
    """Pace a shared sevDesk connection and honor server cooldowns."""

    def __init__(self, *, requests_per_second: int, cooldown_seconds: int) -> None:
        rate = max(0, int(requests_per_second))
        self._interval_seconds = 1.0 / rate if rate else 0.0
        self._cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._next_allowed_at = 0.0
        self._lock = threading.Lock()

    def acquire(self, cancel_token: CancellationToken | None = None) -> None:
        if self._interval_seconds <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                delay = self._next_allowed_at - now
                if delay <= 0:
                    self._next_allowed_at = now + self._interval_seconds
                    return
            # Re-check the shared deadline after sleeping.  Another request may
            # have received a 429 and extended the cooldown in the meantime.
            self._wait(delay, cancel_token)

    def observe(self, response: httpx.Response) -> None:
        if response.status_code != 429:
            return
        delay = self._retry_after_seconds(response.headers.get("Retry-After"))
        if delay is None:
            delay = self._cooldown_seconds
        with self._lock:
            self._next_allowed_at = max(
                self._next_allowed_at,
                time.monotonic() + max(0.0, delay),
            )
        logger.warning("sevDesk rate-limit cooldown active for %.1f seconds", delay)

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return max(0.0, float(text))
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def _wait(delay: float, cancel_token: CancellationToken | None) -> None:
        end_at = time.monotonic() + max(0.0, delay)
        while time.monotonic() < end_at:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            time.sleep(min(0.1, max(0.0, end_at - time.monotonic())))


def build_sevdesk_http_client(config: AppConfig, *, api_token: str | None = None) -> httpx.Client:
    """Create a configured httpx client for sevDesk API v1.

    Authentication: raw API token in ``Authorization`` header (sevDesk convention).
    """
    token = (api_token if api_token is not None else config.sevdesk.api_token or "").strip()
    base = config.sevdesk.base_url.rstrip("/")
    headers = {
        "Authorization": token,
        "Accept": "application/json",
        "User-Agent": "XW-Office sevDesk integration",
    }
    return httpx.Client(base_url=base, headers=headers, timeout=DEFAULT_TIMEOUT)


def humanize_sevdesk_error(status_code: int, body_snippet: str) -> str:
    """Return a short German hint for common HTTP status codes."""
    hint = (body_snippet or "").strip()
    if status_code == 401:
        return "API-Token fehlt oder ist ungueltig (HTTP 401). Bitte SEVDESK_API_TOKEN pruefen."
    if status_code == 403:
        return "Zugriff verweigert (HTTP 403). Token-Rechte oder IP-Schutz pruefen."
    if status_code == 404:
        return f"Ressource nicht gefunden (HTTP 404). {hint}"
    if status_code == 429:
        return (
            "sevDesk Rate-Limit (HTTP 429). Bitte kurz warten und erneut versuchen; "
            "ggf. `sevdesk.rate_limit` in config anpassen."
        )
    if status_code in (500, 502, 503, 504):
        return (
            f"sevDesk-Server voruebergehend nicht erreichbar (HTTP {status_code}). "
            f"{hint}"
        )
    return f"HTTP {status_code}: {hint}"


def raise_for_sevdesk(response: httpx.Response) -> None:
    """Raise :class:`SevdeskApiError` when the response is not successful."""
    if response.is_success:
        return
    text = (response.text[:800] if response.text else "").strip()
    message = humanize_sevdesk_error(response.status_code, text)
    logger.warning("sevDesk HTTP %s: %s", response.status_code, text or message)
    raise SevdeskApiError(message, status_code=response.status_code)


def sevdesk_get_with_retry(
    client: httpx.Client,
    config: AppConfig,
    path: str,
    cancel_token: CancellationToken | None = None,
    max_retries: int | None = None,
    rate_limiter: SevdeskRateLimiter | None = None,
    **kwargs: object,
) -> httpx.Response:
    """GET with retries on transient status codes (safe for read-only calls)."""
    retry_count = max(0, int(config.sevdesk.http_max_retries if max_retries is None else max_retries))
    backoff = float(config.sevdesk.http_retry_backoff_seconds)
    last_response: httpx.Response | None = None

    for attempt in range(retry_count + 1):
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if rate_limiter is not None:
            rate_limiter.acquire(cancel_token)
        response = client.get(path, **kwargs)  # type: ignore[arg-type]
        if rate_limiter is not None:
            rate_limiter.observe(response)
        last_response = response

        if response.is_success:
            return response

        code = response.status_code
        retriable = code in (429, 500, 502, 503, 504)
        if not retriable or attempt >= retry_count:
            raise_for_sevdesk(response)

        retry_after_hdr = response.headers.get("Retry-After")
        delay = backoff * (2**attempt)
        if retry_after_hdr:
            try:
                delay = max(delay, float(retry_after_hdr))
            except ValueError:
                pass
        logger.info(
            "sevDesk GET %s failed with %s, retry %s/%s in %.1fs",
            path,
            code,
            attempt + 1,
            retry_count,
            delay,
        )
        end_at = time.monotonic() + delay
        while time.monotonic() < end_at:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            time.sleep(min(0.1, max(0.0, end_at - time.monotonic())))

    assert last_response is not None
    raise_for_sevdesk(last_response)


@dataclass
class SevdeskReadSession:
    """Reuse identical successful reads only within one thread's calculation."""

    responses: dict[tuple[str, tuple[tuple[str, str], ...]], httpx.Response] = field(
        default_factory=dict
    )
    requests: int = 0
    cache_hits: int = 0
    on_request: Callable[[], None] | None = None


class _ReadSessionLocal(threading.local):
    session: SevdeskReadSession | None = None


@dataclass
class SevdeskConnection:
    """Holds one shared httpx client for all sevDesk service clients."""

    client: httpx.Client
    config: AppConfig
    rate_limiter: SevdeskRateLimiter | None = None
    _read_session: _ReadSessionLocal = field(default_factory=_ReadSessionLocal, init=False)

    @contextmanager
    def read_session(self) -> Generator[SevdeskReadSession, None, None]:
        """Discard all responses on exit; unrelated workers never share this cache."""
        previous = self._read_session.session
        session = SevdeskReadSession()
        self._read_session.session = session
        try:
            yield session
        finally:
            self._read_session.session = previous
            session.responses.clear()
            session.on_request = None

    def get(
        self,
        path: str,
        *,
        max_retries: int | None = None,
        cancel_token: CancellationToken | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        """GET *path* with retry policy from config."""
        session = self._read_session.session
        cache_key = None
        params = kwargs.get("params", {})
        if session is not None and cancel_token is None and not (kwargs.keys() - {"params"}):
            if isinstance(params, dict) and all(
                isinstance(key, str) and isinstance(value, (str, int, float, bool))
                for key, value in params.items()
            ):
                cache_key = (path, tuple(sorted(httpx.QueryParams(params).multi_items())))
                cached = session.responses.get(cache_key)
                if cached is not None:
                    session.cache_hits += 1
                    return httpx.Response(
                        cached.status_code,
                        headers=[
                            (name, value) for name, value in cached.headers.multi_items()
                            if name.lower() not in {"content-encoding", "content-length"}
                        ],
                        content=cached.content,
                        request=cached.request,
                    )
        if session is not None:
            session.requests += 1
            if session.on_request is not None:
                session.on_request()
        response = sevdesk_get_with_retry(
            self.client,
            self.config,
            path,
            cancel_token=cancel_token,
            max_retries=max_retries,
            rate_limiter=self.rate_limiter,
            **kwargs,
        )
        if session is not None and cache_key is not None:
            session.responses[cache_key] = response
        return response

    def _write_request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        if self.rate_limiter is not None:
            self.rate_limiter.acquire()
        request = getattr(self.client, method)
        response: httpx.Response = request(path, **kwargs)
        if self.rate_limiter is not None:
            self.rate_limiter.observe(response)
        raise_for_sevdesk(response)
        return response

    def put(self, path: str, **kwargs: object) -> httpx.Response:
        """PUT *path* (no retry — write operations are not idempotent-safe)."""
        return self._write_request("put", path, **kwargs)

    def patch(self, path: str, **kwargs: object) -> httpx.Response:
        """PATCH *path* (no retry; write operations are not idempotent-safe)."""
        return self._write_request("patch", path, **kwargs)

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        """POST *path* (no retry — write operations are not idempotent-safe)."""
        return self._write_request("post", path, **kwargs)

    def delete(self, path: str, **kwargs: object) -> httpx.Response:
        """DELETE *path* (no retry — write operations are not idempotent-safe)."""
        return self._write_request("delete", path, **kwargs)


def build_sevdesk_connection(config: AppConfig, *, api_token: str | None = None) -> SevdeskConnection:
    """Factory for DI registration."""
    return SevdeskConnection(
        client=build_sevdesk_http_client(config, api_token=api_token),
        config=config,
        rate_limiter=SevdeskRateLimiter(
            requests_per_second=config.sevdesk.rate_limit.requests_per_second,
            cooldown_seconds=config.sevdesk.rate_limit.cooldown_seconds,
        ),
    )
