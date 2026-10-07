"""XW-Flow bridge client for manual/bar/private expenses."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx

from xw_office.core.config import AppConfig
from xw_office.services.secrets.service import SecretService


@dataclass(frozen=True)
class FlowExpense:
    id: str
    version: int
    tenant_key: str
    category_key: str
    category_label_snapshot: str
    expense_date: str | None
    gross_amount: Decimal | None
    tax_rate_bps: int | None
    recipient: str
    purpose: str
    payment_source: str
    receipt_state: str
    accounting_status: str
    reimbursement_status: str
    source_url: str
    note: str


class XwFlowExpenseClient:
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

    @staticmethod
    def _parse(raw: dict[str, Any]) -> FlowExpense:
        amount = raw.get("gross_amount")
        return FlowExpense(
            id=str(raw.get("id") or ""),
            version=int(raw.get("version") or 1),
            tenant_key=str(raw.get("tenant_key") or ""),
            category_key=str(raw.get("category_key") or ""),
            category_label_snapshot=str(raw.get("category_label_snapshot") or ""),
            expense_date=str(raw.get("expense_date") or "") or None,
            gross_amount=Decimal(str(amount)) if amount is not None else None,
            tax_rate_bps=int(raw["tax_rate_bps"]) if raw.get("tax_rate_bps") is not None else None,
            recipient=str(raw.get("recipient") or ""),
            purpose=str(raw.get("purpose") or ""),
            payment_source=str(raw.get("payment_source") or ""),
            receipt_state=str(raw.get("receipt_state") or ""),
            accounting_status=str(raw.get("accounting_status") or ""),
            reimbursement_status=str(raw.get("reimbursement_status") or ""),
            source_url=str(raw.get("source_url") or ""),
            note=str(raw.get("note") or ""),
        )

    def fetch(self, *, tenant_key: str, start: date, end: date, active_only: bool = False) -> list[FlowExpense]:
        connection = self._connection()
        if connection is None:
            return []
        base_url, headers, timeout = connection
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.get(
                "/api/v1/office-bridge/expense-captures",
                params={
                    "tenant_key": tenant_key,
                    "date_from": start.isoformat(),
                    "date_to": end.isoformat(),
                    "active_only": str(active_only).lower(),
                },
            )
            response.raise_for_status()
            payload = response.json()
        values = payload.get("captures") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            raise TypeError("XW-Flow Ausgabenantwort hat ein unbekanntes Format.")
        return [self._parse(item) for item in values if isinstance(item, dict) and item.get("id")]

    def create(
        self,
        *,
        tenant_key: str,
        category_key: str,
        category_label: str,
        amount: Decimal,
        expense_date: date,
        recipient: str,
        purpose: str,
        tax_rate_bps: int | None,
        payment_source: str,
        note: str = "",
    ) -> FlowExpense:
        connection = self._connection()
        if connection is None:
            raise RuntimeError("XW-Flow Ausgaben-Bridge ist nicht konfiguriert")
        base_url, headers, timeout = connection
        payload = {
            "client_request_id": str(uuid4()),
            "tenant_key": tenant_key,
            "category_key": category_key,
            "category_label_snapshot": category_label,
            "source_kind": "desktop_manual",
            "expense_date": expense_date.isoformat(),
            "gross_amount": str(amount),
            "currency": "EUR",
            "tax_mode": "single_rate" if tax_rate_bps is not None else "unknown",
            "tax_rate_bps": tax_rate_bps,
            "recipient": recipient or None,
            "purpose": purpose or None,
            "note": note or None,
            "payment_source": payment_source,
            "receipt_state": "later",
        }
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.post("/api/v1/office-bridge/expense-captures", json=payload)
            response.raise_for_status()
        return self._parse(response.json())

    def update_category(self, *, expense_id: str, version: int, category_key: str, category_label: str) -> FlowExpense:
        connection = self._connection()
        if connection is None:
            raise RuntimeError("XW-Flow Ausgaben-Bridge ist nicht konfiguriert")
        base_url, headers, timeout = connection
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.patch(
                f"/api/v1/office-bridge/expense-captures/{expense_id}",
                json={"version": version, "category_key": category_key, "category_label_snapshot": category_label},
            )
            response.raise_for_status()
        return self._parse(response.json())

    def sync_categories(self, *, tenant_key: str, positions: list[dict[str, object]]) -> None:
        connection = self._connection()
        if connection is None or not positions:
            return
        base_url, headers, timeout = connection
        categories = [
            {
                "tenant_key": tenant_key,
                "category_key": str(position.get("key") or "").strip().lower(),
                "label": str(position.get("label") or "").strip(),
                "initials": str(position.get("initials") or "").strip().upper(),
                "color": str(position.get("color") or "#777777").strip(),
                "enabled": bool(position.get("enabled", True)),
            }
            for position in positions
            if str(position.get("key") or "").strip()
        ]
        with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
            response = client.put(
                "/api/v1/office-bridge/expense-categories/snapshot",
                json={"categories": categories},
            )
            response.raise_for_status()
