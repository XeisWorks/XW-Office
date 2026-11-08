from __future__ import annotations

from tests.unit.test_invoice_inventory_booking import _factory
from xw_office.services.product_hub.invoice_inventory import InvoiceInventoryBookingService, InvoiceInventoryLine
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.sevdesk_credit_note_inventory import SevdeskCreditNoteInventoryService


class _Provider:
    def list_credit_notes_for_year(self, year: int):
        return [
            {"id": "credit-1", "status": 200, "invoiceId": "invoice-1"},
            {"id": "credit-ambiguous", "status": 200},
        ]

    def list_credit_note_positions(self, credit_note_id: str):
        if credit_note_id == "credit-1":
            return [{"id": "credit-pos-1", "invoicePosId": "pos-1", "quantity": 1, "part": {"number": "XW-BOOKING"}}]
        return []


def test_credit_feed_only_processes_unambiguous_origin() -> None:
    factory, variant_id = _factory()
    inventory = InventoryV2Service(factory)
    inventory.record_movement(variant_id=variant_id, delta=10, reason="import_baseline", source="test", idempotency_key="credit-feed-baseline")
    booking = InvoiceInventoryBookingService(factory)
    booking.apply_line(InvoiceInventoryLine("invoice-1", "pos-1", variant_id, 2))
    result = SevdeskCreditNoteInventoryService(_Provider(), booking).process_year(2026)
    assert result.processed == 1
    assert any("Ursprungsrechnung" in issue for issue in result.needs_review)
