from __future__ import annotations

import pytest

from xw_office.models.inventory_document_booking import InventoryDocumentBooking
from tests.unit.test_invoice_inventory_booking import _factory
from xw_office.services.product_hub.invoice_inventory import InvoiceInventoryBookingService
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.sevdesk_invoice_inventory import SevdeskInvoiceInventoryPoller


class _Provider:
    def list_final_invoices(self, *, since=None):
        return [{"id": "external-invoice", "status": 200, "updated": "2026-11-08"}, {"id": "draft", "status": 100}]

    def list_invoice_positions(self, invoice_id: str):
        return [{"id": "pos-1", "quantity": 2, "part": {"number": "XW-BOOKING"}}]


class _OneInvoiceProvider:
    def __init__(self, document: dict, position: dict) -> None:
        self.document = document
        self.position = position

    def list_final_invoices(self, *, since=None):
        return [self.document]

    def list_invoice_positions(self, invoice_id: str):
        return [self.position]


def test_external_invoice_poll_books_final_position_once() -> None:
    factory, variant_id = _factory()
    InventoryV2Service(factory).record_movement(variant_id=variant_id, delta=10, reason="import_baseline", source="test", idempotency_key="poll-baseline")
    result = SevdeskInvoiceInventoryPoller(_Provider(), InvoiceInventoryBookingService(factory)).poll()
    assert result.processed == 1
    repeated = SevdeskInvoiceInventoryPoller(_Provider(), InvoiceInventoryBookingService(factory)).poll()
    assert repeated.already_applied == 1


@pytest.mark.parametrize("quantity", ["0.5", "1.5", "NaN", "Infinity", "not-a-number", None])
def test_invoice_feed_rejects_fractional_or_invalid_quantities(quantity: object) -> None:
    factory, _variant_id = _factory()
    provider = _OneInvoiceProvider(
        {"id": "external-bad-quantity", "status": 200},
        {"id": "position-1", "quantity": quantity, "part": {"number": "XW-BOOKING"}},
    )

    result = SevdeskInvoiceInventoryPoller(provider, InvoiceInventoryBookingService(factory)).poll()

    assert result.processed == 0
    assert len(result.needs_review) == 1
    with factory() as session:
        assert session.query(InventoryDocumentBooking).count() == 0


def test_external_invoice_poll_uses_bulk_positions_when_provider_supports_it() -> None:
    factory, variant_id = _factory()
    InventoryV2Service(factory).record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="poll-bulk-baseline",
    )

    class BulkProvider(_Provider):
        def list_final_invoices(self, *, since=None):
            return [{"id": "bulk-invoice", "status": 200, "updated": "2026-11-08"}]

        def list_invoice_positions(self, invoice_id: str):
            raise AssertionError("bulk provider must avoid per-document position reads")

        def list_invoice_positions_bulk(self, invoice_ids: list[str]):
            assert invoice_ids == ["bulk-invoice"]
            return [{"invoice": {"id": "bulk-invoice"}, "id": "bulk-pos", "quantity": 2, "part": {"number": "XW-BOOKING"}}]

    result = SevdeskInvoiceInventoryPoller(BulkProvider(), InvoiceInventoryBookingService(factory)).poll()
    assert result.processed == 1


def test_invoice_feed_reads_nested_sevdesk_part_number() -> None:
    factory, variant_id = _factory()
    InventoryV2Service(factory).record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="poll-nested-sku-baseline",
    )

    class NestedPartProvider(_OneInvoiceProvider):
        pass

    provider = NestedPartProvider(
        {"id": "nested-part-invoice", "status": 200},
        {"id": "nested-part-position", "quantity": 1, "part": {"partNumber": "XW-BOOKING"}},
    )
    result = SevdeskInvoiceInventoryPoller(provider, InvoiceInventoryBookingService(factory)).poll()
    assert result.processed == 1


def test_invoice_feed_requires_explicit_final_status_and_position_id() -> None:
    factory, _variant_id = _factory()
    provider = _OneInvoiceProvider(
        {"id": "external-unknown-status", "status": 50},
        {"positionNumber": 1, "quantity": 2, "part": {"number": "XW-BOOKING"}},
    )

    result = SevdeskInvoiceInventoryPoller(provider, InvoiceInventoryBookingService(factory)).poll()

    assert result.processed == 0
    assert any("Status" in issue for issue in result.needs_review)
    with factory() as session:
        assert session.query(InventoryDocumentBooking).count() == 0


def test_invoice_feed_does_not_invent_position_identity_from_display_number() -> None:
    factory, _variant_id = _factory()
    provider = _OneInvoiceProvider(
        {"id": "external-no-position-id", "status": 200},
        {"positionNumber": 1, "quantity": 2, "part": {"number": "XW-BOOKING"}},
    )

    result = SevdeskInvoiceInventoryPoller(provider, InvoiceInventoryBookingService(factory)).poll()

    assert result.processed == 0
    assert any("stabile Positions-ID" in issue for issue in result.needs_review)
    with factory() as session:
        assert session.query(InventoryDocumentBooking).count() == 0


def test_invoice_feed_exposes_hub_shortage_without_booking() -> None:
    factory, variant_id = _factory()
    provider = _OneInvoiceProvider(
        {"id": "external-shortage", "status": 200},
        {"id": "position-shortage", "quantity": 2, "part": {"number": "XW-BOOKING"}},
    )
    shortages: list[tuple[object, Exception]] = []

    result = SevdeskInvoiceInventoryPoller(
        provider,
        InvoiceInventoryBookingService(factory),
        on_shortage=lambda line, error: shortages.append((line, error)),
    ).poll()

    assert result.processed == 0
    assert len(result.needs_review) == 1
    assert len(shortages) == 1
    assert shortages[0][0].variant_id == variant_id
    with factory() as session:
        assert session.query(InventoryDocumentBooking).count() == 0
