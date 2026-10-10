"""Authenticated client for the XW-Flow open-print bridge."""
from __future__ import annotations

from dataclasses import dataclass
import httpx

from xw_office.core.config import AppConfig
from xw_office.services.secrets.service import SecretService


@dataclass(frozen=True)
class FlowPrintCase:
    id: str
    title: str
    body_text: str
    source_url: str
    created_at: str


@dataclass(frozen=True)
class FlowPrintEmailCase:
    external_id: str
    title: str
    received_at: str


class XwFlowPrintClient:
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

    def fetch_open_cases(self) -> list[FlowPrintCase]:
        connection = self._connection()
        if connection is None:
            return []
        base_url, headers, timeout = connection
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.get("/api/v1/office-bridge/print-cases")
            response.raise_for_status()
            payload = response.json()
        values = payload.get("cases") if isinstance(payload, dict) else []
        return [FlowPrintCase(id=str(item.get("id") or ""), title=str(item.get("title") or "Neuer Druckauftrag"), body_text=str(item.get("body_text") or ""), source_url=str(item.get("source_url") or ""), created_at=str(item.get("created_at") or "")) for item in values if isinstance(item, dict) and str(item.get("id") or "").strip()]

    def set_status(self, case_id: str, *, completed: bool) -> None:
        connection = self._connection()
        if connection is None:
            raise RuntimeError("XW-Flow Druck-Bridge ist nicht konfiguriert")
        base_url, headers, timeout = connection
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.patch(f"/api/v1/office-bridge/print-cases/{case_id}", json={"status": "completed" if completed else "open"})
            response.raise_for_status()

    def sync_print_email_cases(self, cases: list[FlowPrintEmailCase]) -> None:
        connection = self._connection()
        if connection is None:
            return
        base_url, headers, timeout = connection
        payload = {"cases": [{"external_id": case.external_id, "title": case.title[:300], "received_at": case.received_at or None} for case in cases]}
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.put("/api/v1/office-bridge/print-cases/email-snapshot", json=payload)
            response.raise_for_status()

    def fetch_completed_email_request_ids(self) -> set[str]:
        connection = self._connection()
        if connection is None:
            return set()
        base_url, headers, timeout = connection
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.get("/api/v1/office-bridge/print-cases/email-completions")
            response.raise_for_status()
            payload = response.json()
        values = payload.get("client_request_ids") if isinstance(payload, dict) else []
        return {str(value).strip() for value in values if str(value).strip()}
