"""Central sevDesk web links used by finance and document views."""
from __future__ import annotations

from urllib.parse import quote


def sevdesk_document_url(base_url: str, resource_type: str, external_id: str) -> str:
    """Return a sevDesk UI deep link without leaking the API path."""
    base = (base_url or "https://my.sevdesk.de/api/v1").rstrip("/")
    base = base.removesuffix("/api/v1")
    type_code = {
        "Invoice": "RE",
        "Voucher": "VB",
        "CreditNote": "GS",
    }.get(resource_type, resource_type)
    return f"{base}/fi/detail/type/{quote(type_code)}/id/{quote(str(external_id).strip())}"
