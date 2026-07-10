"""Shared httpx factory and helpers for external REST APIs."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from xw_studio.core.config import AppConfig
from xw_studio.core.exceptions import SevdeskApiError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def build_sevdesk_http_client(config: AppConfig, *, api_token: str | None = None) -> httpx.Client:
    """Create a configured httpx client for sevDesk API v1.

    Authentication: raw API token in ``Authorization`` header (sevDesk convention).
    """
    token = (api_token if api_token is not None else config.sevdesk.api_token or "").strip()
    base = config.sevdesk.base_url.rstrip("/")
    headers = {
        "Authorization": token,
        "Accept": "application/json",
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
    **kwargs: object,
) -> httpx.Response:
    """GET with retries on transient status codes (safe for read-only calls)."""
    max_retries = max(0, int(config.sevdesk.http_max_retries))
    backoff = float(config.sevdesk.http_retry_backoff_seconds)
    last_response: httpx.Response | None = None

    for attempt in range(max_retries + 1):
        response = client.get(path, **kwargs)  # type: ignore[arg-type]
        last_response = response

        if response.is_success:
            return response

        code = response.status_code
        retriable = code in (429, 500, 502, 503, 504)
        if not retriable or attempt >= max_retries:
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
            max_retries,
            delay,
        )
        time.sleep(delay)

    assert last_response is not None
    raise_for_sevdesk(last_response)


@dataclass
class SevdeskConnection:
    """Holds one shared httpx client for all sevDesk service clients."""

    client: httpx.Client
    config: AppConfig

    def get(self, path: str, **kwargs: object) -> httpx.Response:
        """GET *path* with retry policy from config."""
        return sevdesk_get_with_retry(self.client, self.config, path, **kwargs)

    def put(self, path: str, **kwargs: object) -> httpx.Response:
        """PUT *path* (no retry — write operations are not idempotent-safe)."""
        response: httpx.Response = self.client.put(path, **kwargs)  # type: ignore[arg-type]
        raise_for_sevdesk(response)
        return response

    def patch(self, path: str, **kwargs: object) -> httpx.Response:
        """PATCH *path* (no retry; write operations are not idempotent-safe)."""
        response: httpx.Response = self.client.patch(path, **kwargs)  # type: ignore[arg-type]
        raise_for_sevdesk(response)
        return response

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        """POST *path* (no retry — write operations are not idempotent-safe)."""
        response: httpx.Response = self.client.post(path, **kwargs)  # type: ignore[arg-type]
        raise_for_sevdesk(response)
        return response

    def delete(self, path: str, **kwargs: object) -> httpx.Response:
        """DELETE *path* (no retry — write operations are not idempotent-safe)."""
        response: httpx.Response = self.client.delete(path, **kwargs)  # type: ignore[arg-type]
        raise_for_sevdesk(response)
        return response


def build_sevdesk_connection(config: AppConfig, *, api_token: str | None = None) -> SevdeskConnection:
    """Factory for DI registration."""
    return SevdeskConnection(
        client=build_sevdesk_http_client(config, api_token=api_token),
        config=config,
    )
