"""Small authenticated client for XW-Flow share-created shipment cases."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from xw_office.core.config import AppConfig
from xw_office.services.secrets.service import SecretService


@dataclass(frozen=True)
class FlowShipmentCase:
    id: str
    title: str
    body_text: str
    source_url: str
    created_at: str


class XwFlowShipmentClient:
    def __init__(self, config: AppConfig, secrets: SecretService) -> None:
        self._config = config
        self._secrets = secrets

    def _connection(self) -> tuple[str, dict[str, str], float] | None:
        base_url = self._config.flow_shipping_api.base_url.strip().rstrip("/")
        secret = self._secrets.get_secret("XW_OFFICE_BRIDGE_SECRET").strip()
        if not base_url or not secret:
            return None
        return base_url, {"X-XW-Office-Secret": secret}, max(1.0, self._config.flow_shipping_api.timeout_seconds)

    def is_configured(self) -> bool:
        return self._connection() is not None

    def fetch_open_cases(self) -> list[FlowShipmentCase]:
        connection = self._connection()
        if connection is None:
            return []
        base_url, headers, timeout = connection
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.get("/api/v1/office-bridge/shipment-cases")
            response.raise_for_status()
            payload = response.json()
        raw_cases = payload.get("cases") if isinstance(payload, dict) else None
        if not isinstance(raw_cases, list):
            raise TypeError("XW-Flow Sendungsantwort hat ein unbekanntes Format.")
        cases: list[FlowShipmentCase] = []
        for raw in raw_cases:
            if not isinstance(raw, dict):
                continue
            case_id = str(raw.get("id") or "").strip()
            if not case_id:
                continue
            cases.append(
                FlowShipmentCase(
                    id=case_id,
                    title=str(raw.get("title") or "Neue Lieferung").strip(),
                    body_text=str(raw.get("body_text") or "").strip(),
                    source_url=str(raw.get("source_url") or "").strip(),
                    created_at=str(raw.get("created_at") or "").strip(),
                )
            )
        return cases

    def set_status(self, case_id: str, *, completed: bool) -> None:
        connection = self._connection()
        if connection is None:
            raise RuntimeError("XW-Flow Versand-Bridge ist nicht konfiguriert")
        base_url, headers, timeout = connection
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.patch(
                f"/api/v1/office-bridge/shipment-cases/{case_id}",
                json={"status": "completed" if completed else "open"},
            )
            response.raise_for_status()
