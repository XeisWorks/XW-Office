"""Complete, validated sevDesk tax-source pagination."""
from __future__ import annotations

from typing import Any

from xw_office.services.http_client import SevdeskConnection


class TaxPageLimitError(RuntimeError):
    """The source exceeded the explicitly bounded pagination budget."""


def load_tax_resource(
    connection: SevdeskConnection,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    page_size: int = 1000,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for page in range(max_pages):
        query = dict(params or {})
        query.update({"limit": page_size, "offset": page * page_size})
        payload = connection.get(path, params=query).json()
        if not isinstance(payload, dict):
            raise ValueError(f"Steuern: Ungueltige sevDesk-Antwort fuer {path}.")
        objects = payload.get("objects")
        if objects is None:
            return documents
        if not isinstance(objects, list) or any(not isinstance(item, dict) for item in objects):
            raise ValueError(f"Steuern: Ungueltige sevDesk-Objektliste fuer {path}.")
        documents.extend(objects)
        if len(objects) < page_size:
            return documents
    raise TaxPageLimitError(f"Steuern: Seitenlimit fuer {path} erreicht; Daten nicht vollstaendig.")
