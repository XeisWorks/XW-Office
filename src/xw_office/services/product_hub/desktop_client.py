"""Authenticated read-only Product Hub client for XW-Office Desktop."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


class ProductHubDesktopClientError(RuntimeError):
    """Hub is unreachable, rejected the desktop credential, or broke its contract."""


@dataclass(frozen=True)
class DesktopHubSnapshot:
    contract_version: str
    product: dict[str, Any]
    variants: list[dict[str, Any]]
    assets: list[dict[str, Any]]


class ProductHubDesktopClient:
    """Small version-pinned client; it has no write methods by design."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token.strip()
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    def get_product_snapshot(self, product_id: str) -> DesktopHubSnapshot:
        if not self._base_url or not self._token:
            raise ProductHubDesktopClientError("Product-Hub-Desktop-API ist nicht konfiguriert.")
        path = f"/api/v1/desktop/products/{quote(str(product_id), safe='')}/snapshot"
        try:
            with httpx.Client(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.get(path)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProductHubDesktopClientError(f"Product-Hub-Desktop-Lesezugriff fehlgeschlagen: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("contract_version") != "v1":
            raise ProductHubDesktopClientError("Inkompatibler Product-Hub-Desktop-Vertrag.")
        product = payload.get("product")
        variants = payload.get("variants")
        assets = payload.get("assets")
        if not isinstance(product, dict) or not isinstance(variants, list) or not isinstance(assets, list):
            raise ProductHubDesktopClientError("Unvollständiger Product-Hub-Desktop-Vertrag.")
        return DesktopHubSnapshot("v1", product, variants, assets)
