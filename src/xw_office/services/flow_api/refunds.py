"""Read-only refund document feed from wix-sevdesk-api."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from xw_office.core.config import AppConfig
    from xw_office.services.secrets.service import SecretService


class FlowRefundsClient:
    def __init__(self, config: AppConfig, secrets: SecretService) -> None:
        self._config = config
        self._secrets = secrets

    def list_refunds(
        self, *, process_status: str = "", search: str = "", limit: int = 200, offset: int = 0,
    ) -> list[dict[str, Any]]:
        base_url = (self._config.flow_api.base_url or "").strip().rstrip("/")
        secret = self._secrets.get_secret("XW_FLOW_API_SECRET")
        if not base_url:
            raise RuntimeError("XW-FLOW-API-Basis-URL ist nicht konfiguriert.")
        if not secret:
            raise RuntimeError("XW_FLOW_API_SECRET ist nicht konfiguriert.")
        params = {"limit": str(max(1, min(int(limit), 500))), "offset": str(max(0, int(offset)))}
        if process_status:
            params["processStatus"] = process_status
        if search:
            params["search"] = search
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            response = client.get("/api/v1/refunds", params=params, headers={"x-api-key": secret})
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("refunds") if isinstance(payload, dict) else payload
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def list_all_refunds(self) -> list[dict[str, Any]]:
        """Fetch the complete refund ledger; stop if pagination becomes inconsistent."""
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_size = 500
        for offset in range(0, 10_000, page_size):
            page = self.list_refunds(limit=page_size, offset=offset)
            for row in page:
                refund_id = str(row.get("wix_refund_id") or "").strip()
                if not refund_id or refund_id in seen:
                    raise RuntimeError("Wix-Refund-Liste ist unvollstaendig oder instabil.")
                seen.add(refund_id)
                rows.append(row)
            if len(page) < page_size:
                return rows
        raise RuntimeError("Wix-Refund-Liste ueberschreitet die sichere Abrufgrenze.")
