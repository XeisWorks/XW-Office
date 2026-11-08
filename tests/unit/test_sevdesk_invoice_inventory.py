from __future__ import annotations

from tests.unit.test_invoice_inventory_booking import _factory
from xw_office.services.product_hub.invoice_inventory import InvoiceInventoryBookingService
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.sevdesk_invoice_inventory import SevdeskInvoiceInventoryPoller


class _Provider:
    def list_final_invoices(self, *, since=None):
        return [{"id": "external-invoice", "status": 200, "updated": "2026-11-08"}, {"id": "draft", "status": 100}]

    def list_invoice_positions(self, invoice_id: str):
        return [{"id": "pos-1", "quantity": 2, "part": {"number": "XW-BOOKING"}}]


def test_external_invoice_poll_books_final_position_once() -> None:
    factory, variant_id = _factory()
    InventoryV2Service(factory).record_movement(variant_id=variant_id, delta=10, reason="import_baseline", source="test", idempotency_key="poll-baseline")
    result = SevdeskInvoiceInventoryPoller(_Provider(), InvoiceInventoryBookingService(factory)).poll()
    assert result.processed == 1
    repeated = SevdeskInvoiceInventoryPoller(_Provider(), InvoiceInventoryBookingService(factory)).poll()
    assert repeated.already_applied == 1
