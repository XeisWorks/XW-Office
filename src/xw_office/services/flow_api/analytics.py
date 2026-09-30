"""Read-only aggregate analytics client for wix-sevdesk-api."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from xw_office.core.config import AppConfig
    from xw_office.services.secrets.service import SecretService


class FlowAnalyticsClient:
    """Fetch aggregate webshop analytics without exposing admin credentials."""

    def __init__(self, config: AppConfig, secrets: SecretService) -> None:
        self._config = config
        self._secrets = secrets

    def load_summary(self, period: dict[str, Any] | None = None) -> dict[str, Any]:
        base_url = (self._config.flow_api.base_url or "").strip().rstrip("/")
        secret = self._secrets.get_secret("XW_FLOW_API_SECRET")
        if not base_url:
            raise RuntimeError("XW_FLOW_API_BASE_URL ist nicht konfiguriert.")
        if not secret:
            raise RuntimeError("XW_FLOW_API_SECRET ist nicht konfiguriert.")

        params = self._period_params(period or {"type": "days", "days": 90})
        timeout = max(1.0, float(self._config.flow_api.timeout_seconds))
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            response = client.get(
                "/api/v1/analytics/summary",
                params=params,
                headers={"x-api-key": secret},
            )
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict) or not isinstance(payload.get("analytics"), dict):
            raise RuntimeError("Analytics-Antwort hat ein unbekanntes Format.")
        return payload

    @staticmethod
    def _period_params(period: dict[str, Any]) -> dict[str, str]:
        kind = str(period.get("type") or "days")
        if kind == "year":
            return {"period": "year", "year": str(period.get("year") or "")}
        if kind == "custom":
            return {
                "period": "custom",
                "start": str(period.get("start") or period.get("startDate") or ""),
                "end": str(period.get("end") or period.get("endDate") or ""),
            }
        return {"days": str(period.get("days", 90))}
