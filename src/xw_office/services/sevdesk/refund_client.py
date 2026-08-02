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
