"""Live action dispatcher for XW-Copilot: routes actions to real services.

Used when the XW-Copilot config mode is set to ``live``.  All dependencies
are optional — missing services gracefully return an error preview so the
response contract stays intact even in partially configured environments.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from xw_office.services.crm.service import CrmService
    from xw_office.services.inventory.service import InventoryService
    from xw_office.services.invoice_processing.service import InvoiceProcessingService

logger = logging.getLogger(__name__)


class XWCopilotLiveDispatcher:
    """Route live XW-Copilot actions to the real service layer.

    All service arguments are optional so the dispatcher can be created
    even when some services are unavailable (e.g. no API token).
    """

    def __init__(
        self,
        crm_service: "CrmService | None" = None,
        invoice_processing: "InvoiceProcessingService | None" = None,
        inventory_service: "InventoryService | None" = None,
    ) -> None:
        self._crm = crm_service
        self._invoices = invoice_processing
        self._inventory = inventory_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(self, action: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Execute *action* against real services and return a result dict.

        Returns ``None`` when the action is not supported.
        Errors inside service calls are caught and returned as structured
        ``{"error": "…"}`` dicts so the dry-run response stays valid.
        """
        if action == "crm.lookup_contact":
            return self._crm_lookup(str(payload.get("query") or ""))
        if action == "invoice.read_status":
            return self._invoice_read(str(payload.get("invoice_number") or ""))
        if action == "inventory.start_preflight":
            sku = str(payload.get("sku") or "")
            quantity = int(payload.get("quantity") or 1)
            return self._inventory_preflight(sku, quantity)
        return None

    # ------------------------------------------------------------------
    # Private action implementations
    # ------------------------------------------------------------------

    def _crm_lookup(self, query: str) -> dict[str, Any]:
        if self._crm is None or not self._crm.has_live_connection():
            return {
                "error": "CRM not configured (SEVDESK_API_TOKEN missing).",
                "contacts": [],
            }
        try:
            contacts = self._crm.fetch_live_contacts()
        except Exception as exc:
            logger.warning("CRM live lookup failed: %s", exc)
            return {"error": str(exc), "contacts": []}

        q = query.strip().lower()
        matches = [
            {
                "id": c.id,
                "name": c.name,
                "email": c.email or "",
                "phone": c.phone or "",
                "city": c.city or "",
            }
            for c in contacts
            if not q
            or q in (c.name or "").lower()
            or q in (c.email or "").lower()
            or q in (c.phone or "").lower()
        ]
        return {
            "service": "crm",
            "operation": "lookup_contact",
            "query": query,
            "contacts": matches[:20],
            "total_searched": len(contacts),
        }

    def _invoice_read(self, invoice_number: str) -> dict[str, Any]:
        if self._invoices is None:
            return {
                "error": "Invoice service not configured.",
                "invoices": [],
            }
        try:
            summaries = self._invoices.load_invoice_summaries(limit=200)
        except Exception as exc:
            logger.warning("Invoice live read failed: %s", exc)
            return {"error": str(exc), "invoices": []}

        matches = [
            {
                "id": s.id,
                "number": s.invoice_number or "",
                "status": s.status_label(),
                "sum_gross": str(s.sum_gross) if s.sum_gross is not None else "",
                "contact": s.contact_name or "",
                "date": s.invoice_date or "",
            }
            for s in summaries
            if not invoice_number or invoice_number in (s.invoice_number or "")
        ][:10]
        return {
            "service": "invoices",
            "operation": "read_status",
            "query": invoice_number,
            "invoices": matches,
        }

    def _inventory_preflight(self, sku: str, quantity: int) -> dict[str, Any]:
        if self._inventory is None:
            return {"error": "Inventory service not configured."}
        try:
            preflight = self._inventory.build_start_preflight(open_invoice_count=1)
        except Exception as exc:
            logger.warning("Inventory preflight failed: %s", exc)
            return {"error": str(exc)}

        decisions = [
            {
                "sku": d.sku,
                "on_hand": d.on_hand_qty,
                "required": d.required_qty,
                "missing": d.missing_qty,
                "will_print": d.will_print,
                "print_qty": d.final_print_qty,
            }
            for d in preflight.decisions
            if not sku or d.sku == sku
        ]
        return {
            "service": "inventory",
            "operation": "start_preflight",
            "sku_filter": sku,
            "requested_quantity": quantity,
            "decisions": decisions,
            "missing_position_data": preflight.missing_position_data,
        }
