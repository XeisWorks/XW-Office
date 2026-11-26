"""EDU management commands against the Wix backend and invoice routing reads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from xw_office.services.secrets.service import SecretService

_EMAIL = re.compile(r"[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+")


@dataclass(frozen=True)
class EduInvoiceRoute:
    to: str
    cc: str
    target: str


class EduClient:
    def __init__(self, secrets: SecretService, *, transport: httpx.BaseTransport | None = None):
        self._secrets = secrets
        self._transport = transport

    def _url(self, name: str, path: str) -> str:
        base = self._secrets.get_secret(name).rstrip("/")
        parts = urlsplit(base)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.query
            or parts.fragment
        ):
            raise RuntimeError(f"{name} muss auf einen HTTPS-Endpunkt zeigen.")
        return base + path

    def _key(self, name: str) -> str:
        key = self._secrets.get_secret(name)
        if len(key) < 32:
            raise RuntimeError(f"{name} ist nicht konfiguriert.")
        return key

    def _request(
        self, method: str, url: str, headers: dict[str, str], **kwargs: Any
    ) -> httpx.Response:
        try:
            with httpx.Client(transport=self._transport, timeout=12) as client:
                return client.request(method, url=url, headers=headers, **kwargs)
        except httpx.RequestError:
            raise RuntimeError("Der EDU-Dienst ist derzeit nicht erreichbar.") from None

    def command(self, operation: str, **fields: Any) -> dict[str, Any]:
        url = self._url("EDU_WIX_ORIGIN", "/_functions/xw_edu_admin")
        key = self._key("EDU_OFFICE_SECRET")
        response = self._request(
            "POST", url, {"x-edu-office-key": key}, json={"operation": operation, **fields}
        )
        try:
            result = response.json()
        except ValueError:
            result = {}
        if not response.is_success or not isinstance(result, dict):
            code = result.get("error", "") if isinstance(result, dict) else ""
            messages = {
                "EDU_VERSION_CONFLICT": "Der Datensatz wurde geändert. Bitte neu laden.",
                "EDU_ACTION_FORBIDDEN": "Die Voraussetzungen für diese Aktion sind noch nicht erfüllt.",
                "EDU_BILLING_FIELDS_INVALID": "Bitte prüfe die Rechnungsdaten.",
                "EDU_AUTH_REQUIRED": "Der EDU-Zugang zu Wix ist nicht eingerichtet.",
            }
            raise RuntimeError(
                messages.get(code, f"EDU-Dienst meldet HTTP {response.status_code}.")
            )
        return result

    def invoice_route(self, invoice_id: str) -> EduInvoiceRoute:
        if re.fullmatch(r"\d{1,30}", invoice_id) is None:
            raise RuntimeError("Die EDU-Rechnung hat keine gültige Beleg-ID.")
        url = self._url("EDU_INVOICE_BRIDGE_ORIGIN", f"/api/v1/edu-invoice-routing/{invoice_id}")
        key = self._key("EDU_INVOICE_READ_SECRET")
        response = self._request("GET", url, {"x-api-key": key})
        if not response.is_success:
            raise RuntimeError("Der bestätigte EDU-Rechnungsempfänger ist derzeit nicht verfügbar.")
        data = response.json()
        to = str(data.get("to") or "")
        cc = str(data.get("cc") or "")
        target = str(data.get("target") or "")
        if (
            not _EMAIL.fullmatch(to)
            or (cc and not _EMAIL.fullmatch(cc))
            or target not in {"school", "private"}
        ):
            raise RuntimeError("Die EDU-Rechnung enthält ungültige Versanddaten.")
        return EduInvoiceRoute(to=to, cc=cc, target=target)

    def school_orders(self, institution_id: str) -> list[dict[str, Any]]:
        rows = self._order_sync_request("GET", institution_id).get("orders")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("Die EDU-Bridge hat keinen gültigen Sync-Status geliefert.")
        return [row for row in rows if isinstance(row, dict)]

    def retry_school_order(self, institution_id: str, order_id: str) -> None:
        self._order_sync_request("POST", institution_id, order_id)

    def _order_sync_request(
        self, method: str, institution_id: str, order_id: str = ""
    ) -> dict[str, Any]:
        if any(
            not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", item)
            for item in (institution_id, order_id)
            if item
        ):
            raise RuntimeError("Die EDU-Zuordnung hat keine gültige ID.")
        path = f"/api/v1/edu-invoice-routing/schools/{institution_id}"
        secret = "EDU_INVOICE_READ_SECRET"
        if method == "POST":
            path += f"/retry/{order_id}"
            secret = "EDU_INVOICE_RETRY_SECRET"
        response = self._request(
            method, self._url("EDU_INVOICE_BRIDGE_ORIGIN", path), {"x-api-key": self._key(secret)}
        )
        if response.status_code == 409:
            raise RuntimeError(
                "Dieser Vorgang kann in seinem aktuellen Status nicht wiederholt werden."
            )
        if not response.is_success:
            raise RuntimeError("Die EDU-Rechnungspipeline ist derzeit nicht erreichbar.")
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Die EDU-Bridge hat eine ungültige Antwort geliefert.")
        return data
