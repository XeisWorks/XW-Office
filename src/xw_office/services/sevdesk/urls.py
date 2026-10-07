"""Central sevDesk web links used by finance and document views."""
from __future__ import annotations

from urllib.parse import quote


def sevdesk_document_url(base_url: str, resource_type: str, external_id: str) -> str:
    """Return the current sevDesk document-detail deep link.

    The former finance route (``/fi/detail/type/...``) is redirected by the
    current sevDesk UI to the dashboard.  ``/ex/detail/id/...`` works for
    invoices, vouchers and credit notes alike, so no type fragment is needed.
    """
    base = (base_url or "https://my.sevdesk.de/api/v1").rstrip("/")
    base = base.removesuffix("/api/v1")
    return f"{base}/ex/detail/id/{quote(str(external_id).strip())}"
