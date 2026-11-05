"""sevDesk refund / cancellation client.

Provides two operations used by the refund dialog:

1. ``cancel_invoice``  — POST /Invoice/{id}/cancelInvoice
   Creates a Stornorechnung (SR) automatically and books it.
   Source invoice status → "Storniert". Cannot be undone.

2. ``create_credit_note_from_invoice``  — POST /CreditNote/Factory/createFromInvoice
   Creates a Gutschrift DRAFT from an existing invoice (all items copied).
   The draft has zero accounting effect until sent/booked.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from xw_office.services.http_client import SevdeskConnection

logger = logging.getLogger(__name__)


class SevDeskRefundClient:
    """Minimal write client for invoice cancellation and credit note creation."""

    def __init__(self, connection: SevdeskConnection) -> None:
        self._conn = connection

    def cancel_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Cancel an invoice by creating a Stornorechnung (SR) in sevDesk.

        The SR is automatically booked; the source invoice is marked as cancelled.
        Returns the raw API response dict on success.
        Raises :class:`~xw_office.core.exceptions.SevdeskApiError` on failure.
        """
        invoice_id = str(invoice_id).strip()
        logger.info("SevDeskRefundClient: cancelling invoice %s", invoice_id)
        response = self._conn.post(f"/Invoice/{invoice_id}/cancelInvoice")
        payload: dict[str, Any] = response.json() if response.content else {}
        logger.info(
            "SevDeskRefundClient: invoice %s cancelled; response keys=%s",
            invoice_id,
            list(payload.keys()),
        )
        return payload

    def create_credit_note_from_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Create a Gutschrift DRAFT from an existing invoice.

        Uses ``POST /CreditNote/Factory/createFromInvoice``.
        Returns the credit note object from the API.
        Raises :class:`~xw_office.core.exceptions.SevdeskApiError` on failure.
        """
        invoice_id = str(invoice_id).strip()
        logger.info(
            "SevDeskRefundClient: creating credit note from invoice %s", invoice_id
        )
        body = {"invoice": {"id": invoice_id, "objectName": "Invoice"}}
        response = self._conn.post("/CreditNote/Factory/createFromInvoice", json=body)
        payload: dict[str, Any] = response.json() if response.content else {}
        objects = payload.get("objects") or payload
        logger.info(
            "SevDeskRefundClient: credit note created from invoice %s", invoice_id
        )
        return objects if isinstance(objects, dict) else payload

    def fetch_credit_note(self, credit_note_id: str) -> dict[str, Any]:
        response = self._conn.get(f"/CreditNote/{str(credit_note_id).strip()}")
        payload = response.json() if response.content else {}
        objects = payload.get("objects") if isinstance(payload, dict) else payload
        if isinstance(objects, list):
            return next((item for item in objects if isinstance(item, dict)), {})
        return objects if isinstance(objects, dict) else payload if isinstance(payload, dict) else {}

    def get_credit_note_pdf(self, credit_note_id: str) -> bytes:
        response = self._conn.get(f"/CreditNote/{str(credit_note_id).strip()}/getPdf", params={"download": "true", "preventSendBy": "true"})
        if response.content.startswith(b"%PDF"):
            return response.content
        payload = response.json() if response.content else {}
        return self._pdf_from_payload(payload)

    def render_credit_note_pdf(self, credit_note_id: str) -> bytes:
        response = self._conn.post(f"/CreditNote/{str(credit_note_id).strip()}/render", params={"getAsPdf": "true"})
        if response.content.startswith(b"%PDF"):
            return response.content
        return self._pdf_from_payload(response.json() if response.content else {})

    @staticmethod
    def _pdf_from_payload(payload: Any) -> bytes:
        candidates = [payload]
        if isinstance(payload, dict):
            candidates.extend([payload.get("objects"), payload.get("data"), payload.get("pdf")])
        for candidate in candidates:
            if isinstance(candidate, dict):
                for key in ("content", "base64", "pdf", "file"):
                    value = candidate.get(key)
                    if isinstance(value, str):
                        try:
                            decoded = base64.b64decode(value)
                        except Exception:
                            continue
                        if decoded.startswith(b"%PDF"):
                            return decoded
            elif isinstance(candidate, str):
                try:
                    decoded = base64.b64decode(candidate)
                except Exception:
                    continue
                if decoded.startswith(b"%PDF"):
                    return decoded
        raise RuntimeError("sevDesk hat kein gültiges Gutschrift-PDF geliefert.")
