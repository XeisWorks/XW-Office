from __future__ import annotations

import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
import pytest

from xw_office.models.base import Base
from xw_office.models.inventory_document_booking import InventoryDocumentBooking
from xw_office.models.product_hub_inventory import InventoryMovement
from xw_office.models.product_hub import ProductVariant
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.invoice_inventory import (
    InvoiceInventoryBookingService,
    InvoiceInventoryLine,
)
from xw_office.services.invoice_processing.context import normalize_invoice_positions


def _factory() -> tuple[sessionmaker[Session], uuid.UUID]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    product, variant = ProductHubRepository(factory).create_product(
        sku="XW-BOOKING", name="Booking test"
    )
    return factory, variant.id


@pytest.mark.parametrize("quantity", ["0.5", "1.5", "2.9"])
def test_fractional_product_quantity_stops_before_any_booking(quantity: str) -> None:
    factory, _variant_id = _factory()
    service = InvoiceInventoryBookingService(factory)
    positions = normalize_invoice_positions(
        [{"part": {"partNumber": "XW-BOOKING"}, "quantity": quantity}]
    )
    with pytest.raises(ValueError, match="Bruchmenge"):
        service.validate_invoice_context(positions)
    with pytest.raises(ValueError, match="Bruchmenge"):
        service.apply_invoice_context(document_id="fractional", positions=positions)
    with factory() as session:
        assert session.query(InventoryDocumentBooking).count() == 0


def test_unresolved_part_without_sku_is_not_silently_ignored() -> None:
    factory, _variant_id = _factory()
    service = InvoiceInventoryBookingService(factory)
    positions = normalize_invoice_positions(
        [{"part": {"id": "missing-part"}, "quantity": 1}]
    )
    with pytest.raises(ValueError, match="ohne SKU"):
        service.validate_invoice_context(positions)


def test_validate_invoice_context_rejects_shortage_before_release() -> None:
    factory, variant_id = _factory()
    InventoryV2Service(factory).record_movement(
        variant_id=variant_id,
        delta=1,
        reason="import_baseline",
        source="test",
        idempotency_key="preflight-baseline",
    )
    service = InvoiceInventoryBookingService(factory)
    positions = normalize_invoice_positions(
        [{"part": {"partNumber": "XW-BOOKING"}, "quantity": 2}]
    )

    with pytest.raises(ValueError, match="Bestand reicht.*XW-BOOKING"):
        service.validate_invoice_context(positions)
    with factory() as session:
        assert session.query(InventoryDocumentBooking).count() == 0


def test_zero_quantity_does_not_require_a_physical_mapping() -> None:
    factory, _variant_id = _factory()
    service = InvoiceInventoryBookingService(factory)
    positions = normalize_invoice_positions(
        [{"part": {"id": "missing-part"}, "quantity": 0}]
    )
    assert service.apply_invoice_context(document_id="zero", positions=positions) == []


def test_fractional_digital_position_does_not_require_stock_booking() -> None:
    factory, variant_id = _factory()
    with factory() as session:
        variant = session.get(ProductVariant, variant_id)
        assert variant is not None
        variant.stock_enabled = False
        session.commit()
    service = InvoiceInventoryBookingService(factory)
    positions = normalize_invoice_positions(
        [{"part": {"partNumber": "XW-BOOKING"}, "quantity": "0.5"}]
    )
    assert service.apply_invoice_context(document_id="digital", positions=positions) == []


def test_same_finalized_position_is_applied_only_once() -> None:
    factory, variant_id = _factory()
    inventory = InventoryV2Service(factory)
    inventory.record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="booking-baseline",
    )
    booking = InvoiceInventoryBookingService(factory)
    line = InvoiceInventoryLine("invoice-1", "pos-1", variant_id, quantity=2)

    first = booking.apply_line(line)
    second = booking.apply_line(line)

    assert first.status == "applied"
    assert first.delta == -2
    assert second.status == "already_applied"
    assert second.delta == 0
    with factory() as session:
        row = session.query(InventoryDocumentBooking).one()
        assert row.quantity_applied == -2
    stock = InventoryRepository(factory).get_stock(variant_id, InventoryRepository(factory).get_or_create_location(code="MAIN", name="Hauptlager").id)
    assert stock is not None and stock.on_hand == 8


def test_changed_final_quantity_applies_only_the_difference_and_credit_reverses() -> None:
    factory, variant_id = _factory()
    inventory = InventoryV2Service(factory)
    inventory.record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="booking-baseline-2",
    )
    booking = InvoiceInventoryBookingService(factory)
    booking.apply_line(InvoiceInventoryLine("invoice-2", "pos-1", variant_id, 2))
    changed = booking.apply_line(InvoiceInventoryLine("invoice-2", "pos-1", variant_id, 3))
    credit = booking.apply_line(
        InvoiceInventoryLine("invoice-2", "pos-1", variant_id, 1, movement_kind="return")
    )

    assert changed.delta == -1
    assert credit.delta == 1
    location = InventoryRepository(factory).get_or_create_location(code="MAIN", name="Hauptlager")
    stock = InventoryRepository(factory).get_stock(variant_id, location.id)
    assert stock is not None and stock.on_hand == 8


def test_repeated_historical_quantity_gets_a_new_transition_identity() -> None:
    factory, variant_id = _factory()
    inventory = InventoryV2Service(factory)
    inventory.record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="booking-baseline-revision",
    )
    booking = InvoiceInventoryBookingService(factory)
    first = InvoiceInventoryLine("invoice-revision", "pos-1", variant_id, 2)
    assert booking.apply_line(first).delta == -2
    assert booking.apply_line(InvoiceInventoryLine("invoice-revision", "pos-1", variant_id, 3)).delta == -1
    replayed_target = booking.apply_line(first)

    assert replayed_target.delta == 1
    location = InventoryRepository(factory).get_or_create_location(code="MAIN", name="Hauptlager")
    stock = InventoryRepository(factory).get_stock(variant_id, location.id)
    assert stock is not None and stock.on_hand == 8
    with factory() as session:
        movements = session.query(InventoryMovement).filter_by(
            external_reference="invoice-revision:pos-1"
        ).count()
    assert movements == 3


def test_booking_update_failure_rolls_back_ledger_and_stock() -> None:
    factory, variant_id = _factory()
    inventory = InventoryV2Service(factory)
    inventory.record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="booking-baseline-rollback",
    )
    with factory() as session:
        session.execute(text(
            "CREATE TRIGGER reject_invoice_booking_update "
            "BEFORE UPDATE ON inventory_document_booking "
            "BEGIN SELECT RAISE(ABORT, 'injected booking failure'); END"
        ))
        session.commit()

    booking = InvoiceInventoryBookingService(factory)
    with pytest.raises(IntegrityError, match="injected booking failure"):
        booking.apply_line(InvoiceInventoryLine("invoice-rollback", "pos-1", variant_id, 2))

    location = InventoryRepository(factory).get_or_create_location(code="MAIN", name="Hauptlager")
    stock = InventoryRepository(factory).get_stock(variant_id, location.id)
    assert stock is not None and stock.on_hand == 10
    with factory() as session:
        assert session.query(InventoryDocumentBooking).filter_by(
            document_id="invoice-rollback"
        ).count() == 0
        assert session.query(InventoryMovement).filter_by(
            external_reference="invoice-rollback:pos-1"
        ).count() == 0


def test_credit_is_limited_to_original_sale_and_is_idempotent() -> None:
    factory, variant_id = _factory()
    inventory = InventoryV2Service(factory)
    inventory.record_movement(
        variant_id=variant_id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="booking-baseline-3",
    )
    booking = InvoiceInventoryBookingService(factory)
    booking.apply_line(InvoiceInventoryLine("invoice-3", "pos-1", variant_id, 3))
    credit = InvoiceInventoryLine(
        "credit-3",
        "credit-pos-1",
        variant_id,
        2,
        movement_kind="return",
        original_document_id="invoice-3",
        original_position_key="pos-1",
    )

    first = booking.apply_credit_line(credit)
    second = booking.apply_credit_line(credit)

    assert first.delta == 2
    assert second.status == "already_applied"
    with pytest.raises(ValueError, match="Credit quantity"):
        booking.apply_credit_line(
            InvoiceInventoryLine(
                "credit-4",
                "credit-pos-1",
                variant_id,
                2,
                movement_kind="return",
                original_document_id="invoice-3",
                original_position_key="pos-1",
            )
        )
