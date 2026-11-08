from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.inventory_document_booking import InventoryDocumentBooking
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.invoice_inventory import (
    InvoiceInventoryBookingService,
    InvoiceInventoryLine,
)


def _factory() -> tuple[sessionmaker[Session], uuid.UUID]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    product, variant = ProductHubRepository(factory).create_product(
        sku="XW-BOOKING", name="Booking test"
    )
    return factory, variant.id


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
