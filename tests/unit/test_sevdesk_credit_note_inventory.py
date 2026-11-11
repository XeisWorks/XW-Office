from __future__ import annotations

import datetime
import pytest

from xw_office.models.inventory_document_booking import InventoryDocumentBooking
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


class _OneCreditProvider:
    def __init__(self, credit: dict, position: dict) -> None:
        self.credit = credit
        self.position = position

    def list_credit_notes_for_year(self, year: int):
        return [self.credit]

    def list_credit_note_positions(self, credit_note_id: str):
        return [self.position]


def test_credit_feed_only_processes_unambiguous_origin() -> None:
    factory, variant_id = _factory()
    inventory = InventoryV2Service(factory)
    inventory.record_movement(variant_id=variant_id, delta=10, reason="import_baseline", source="test", idempotency_key="credit-feed-baseline")
    booking = InvoiceInventoryBookingService(factory)
    booking.apply_line(InvoiceInventoryLine("invoice-1", "pos-1", variant_id, 2))
    result = SevdeskCreditNoteInventoryService(_Provider(), booking).process_year(2026)
    assert result.processed == 1
    assert any("Ursprungsrechnung" in issue for issue in result.needs_review)


def test_credit_feed_uses_bulk_positions_when_provider_supports_it() -> None:
    factory, variant_id = _factory()
    inventory = InventoryV2Service(factory)
    inventory.record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="credit-bulk-baseline",
    )
    booking = InvoiceInventoryBookingService(factory)
    booking.apply_line(InvoiceInventoryLine("invoice-1", "pos-1", variant_id, 2))

    class BulkProvider(_Provider):
        def list_credit_note_positions(self, credit_note_id: str):
            raise AssertionError("bulk provider must avoid per-document position reads")

        def list_credit_note_positions_bulk(self, credit_note_ids: list[str]):
            assert credit_note_ids == ["credit-1", "credit-ambiguous"]
            return [{"creditNote": {"id": "credit-1"}, "id": "credit-pos-1", "invoicePosId": "pos-1", "quantity": 1, "part": {"number": "XW-BOOKING"}}]

    result = SevdeskCreditNoteInventoryService(BulkProvider(), booking).process_year(2026)
    assert result.processed == 1


def test_credit_feed_since_excludes_pre_inventory_notes() -> None:
    factory, variant_id = _factory()
    inventory = InventoryV2Service(factory)
    inventory.record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="credit-since-baseline",
    )
    booking = InvoiceInventoryBookingService(factory)
    booking.apply_line(InvoiceInventoryLine("invoice-1", "pos-1", variant_id, 2))

    class DatedProvider(_Provider):
        def list_credit_notes_for_year(self, year: int):
            return [
                {"id": "credit-old", "status": 200, "invoiceId": "invoice-1", "creditNoteDate": "2026-01-01"},
                {"id": "credit-new", "status": 200, "invoiceId": "invoice-1", "creditNoteDate": "2026-11-09"},
            ]

        def list_credit_note_positions(self, credit_note_id: str):
            return [{"id": credit_note_id + "-pos", "invoicePosId": "pos-1", "quantity": 1, "part": {"number": "XW-BOOKING"}}]

    result = SevdeskCreditNoteInventoryService(DatedProvider(), booking).process_year(
        2026,
        since=datetime.date(2026, 11, 1),
    )
    assert result.processed == 1
    assert result.needs_review == []


@pytest.mark.parametrize("quantity", ["0.5", "1.5", "NaN", "Infinity", "not-a-number", None])
def test_credit_feed_rejects_fractional_or_invalid_quantities(quantity: object) -> None:
    factory, variant_id = _factory()
    InventoryV2Service(factory).record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="credit-feed-invalid-baseline",
    )
    booking = InvoiceInventoryBookingService(factory)
    booking.apply_line(InvoiceInventoryLine("origin-invoice", "origin-pos", variant_id, 2))
    provider = _OneCreditProvider(
        {"id": "bad-credit", "status": 200, "invoiceId": "origin-invoice"},
        {
            "id": "credit-pos",
            "invoicePosId": "origin-pos",
            "quantity": quantity,
            "part": {"number": "XW-BOOKING"},
        },
    )

    result = SevdeskCreditNoteInventoryService(provider, booking).process_year(2026)

    assert result.processed == 0
    assert len(result.needs_review) == 1
    with factory() as session:
        assert session.query(InventoryDocumentBooking).filter_by(movement_kind="return").count() == 0


def test_credit_feed_requires_final_status_and_stable_position_id() -> None:
    factory, variant_id = _factory()
    InventoryV2Service(factory).record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="credit-feed-identity-baseline",
    )
    booking = InvoiceInventoryBookingService(factory)
    booking.apply_line(InvoiceInventoryLine("origin-invoice", "origin-pos", variant_id, 2))
    provider = _OneCreditProvider(
        {"id": "credit-unknown", "status": 300, "invoiceId": "origin-invoice"},
        {
            "positionNumber": 1,
            "invoicePosId": "origin-pos",
            "quantity": 1,
            "part": {"number": "XW-BOOKING"},
        },
    )

    result = SevdeskCreditNoteInventoryService(provider, booking).process_year(2026)

    assert result.processed == 0
    assert any("Status" in issue for issue in result.needs_review)
    missing_identity = _OneCreditProvider(
        {"id": "credit-missing-position-id", "status": 200, "invoiceId": "origin-invoice"},
        {
            "positionNumber": 1,
            "invoicePosId": "origin-pos",
            "quantity": 1,
            "part": {"number": "XW-BOOKING"},
        },
    )
    identity_result = SevdeskCreditNoteInventoryService(  # type: ignore[arg-type]
        missing_identity, booking
    ).process_year(2026)
    assert identity_result.processed == 0
    assert any("Positions-ID" in issue for issue in identity_result.needs_review)
    with factory() as session:
        assert session.query(InventoryDocumentBooking).filter_by(movement_kind="return").count() == 0
