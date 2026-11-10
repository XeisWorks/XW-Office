"""Opt-in PostgreSQL race tests for invoice inventory bookings.

Set ``XW_TEST_POSTGRES_URL`` to an isolated, disposable PostgreSQL database.
The test creates and drops a uniquely named schema; it never touches the public
schema or the application's ``DATABASE_URL``.
"""
from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import uuid
from typing import cast

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
import pytest

from xw_office.models.base import Base
from xw_office.models.inventory_document_booking import InventoryDocumentBooking
from xw_office.models.product_hub_inventory import InventoryMovement
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.invoice_processing.operation_claims import (
    InvoiceOperationClaimStore,
    OperationClaim,
)
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.invoice_inventory import (
    InvoiceInventoryBookingService,
    InvoiceInventoryBookingResult,
    InvoiceInventoryLine,
)


@pytest.fixture
def postgres_factory() -> Iterator[sessionmaker[Session]]:
    database_url = os.environ.get("XW_TEST_POSTGRES_URL", "").strip()
    if not database_url:
        pytest.skip("XW_TEST_POSTGRES_URL must point to an isolated PostgreSQL test database")

    schema = f"invoice_booking_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(database_url, future=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    scoped_url = make_url(database_url).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(scoped_url, future=True, pool_size=5, max_overflow=5)
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _seed_stock(factory: sessionmaker[Session]) -> uuid.UUID:
    _product, variant = ProductHubRepository(factory).create_product(
        sku="XW-PG-BOOKING", name="PostgreSQL booking test"
    )
    InventoryV2Service(factory).record_movement(
        variant_id=variant.id,
        delta=10,
        reason="import_baseline",
        source="postgres-test",
        idempotency_key=f"baseline:{uuid.uuid4()}",
    )
    return variant.id


def test_parallel_first_booking_applies_one_inventory_movement(
    postgres_factory: sessionmaker[Session],
) -> None:
    factory = postgres_factory
    variant_id = _seed_stock(factory)
    line = InvoiceInventoryLine("pg-invoice-1", "position-1", variant_id, 2)
    barrier = threading.Barrier(2)

    def apply() -> InvoiceInventoryBookingResult:
        barrier.wait(timeout=10)
        return InvoiceInventoryBookingService(factory).apply_line(line)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=30) for future in [pool.submit(apply), pool.submit(apply)]]

    assert sorted(result.status for result in results) == ["already_applied", "applied"]
    location = InventoryRepository(factory).get_or_create_location(code="MAIN", name="Hauptlager")
    stock = InventoryRepository(factory).get_stock(variant_id, location.id)
    assert stock is not None and stock.on_hand == 8
    with factory() as session:
        assert session.query(InventoryDocumentBooking).filter_by(
            document_id="pg-invoice-1", position_key="position-1"
        ).count() == 1
        assert session.query(InventoryMovement).filter_by(
            external_reference="pg-invoice-1:position-1"
        ).count() == 1


def test_parallel_credits_cannot_exceed_sale_quantity(
    postgres_factory: sessionmaker[Session],
) -> None:
    factory = postgres_factory
    variant_id = _seed_stock(factory)
    booking = InvoiceInventoryBookingService(factory)
    booking.apply_line(InvoiceInventoryLine("pg-invoice-2", "position-1", variant_id, 3))
    credits = [
        InvoiceInventoryLine(
            f"pg-credit-{index}",
            "credit-position-1",
            variant_id,
            2,
            movement_kind="return",
            original_document_id="pg-invoice-2",
            original_position_key="position-1",
        )
        for index in (1, 2)
    ]
    barrier = threading.Barrier(2)

    def apply(credit: InvoiceInventoryLine) -> str:
        barrier.wait(timeout=10)
        try:
            return InvoiceInventoryBookingService(factory).apply_credit_line(credit).status
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply, credit) for credit in credits]
        results = [future.result(timeout=30) for future in futures]

    assert sum(result == "applied" for result in results) == 1
    assert sum("exceeds remaining returnable quantity" in result for result in results) == 1
    with factory() as session:
        returned = session.query(InventoryDocumentBooking).filter_by(
            original_document_id="pg-invoice-2",
            original_position_key="position-1",
            movement_kind="return",
        ).one()
        assert returned.quantity_applied == 2


def test_booking_failure_rolls_back_postgres_ledger_and_stock(
    postgres_factory: sessionmaker[Session],
) -> None:
    factory = postgres_factory
    variant_id = _seed_stock(factory)
    engine = cast(Engine, factory.kw["bind"])
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE FUNCTION reject_invoice_booking_update() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected booking failure'; END $$"
        ))
        connection.execute(text(
            "CREATE TRIGGER reject_invoice_booking_update BEFORE UPDATE "
            "ON inventory_document_booking FOR EACH ROW "
            "EXECUTE FUNCTION reject_invoice_booking_update()"
        ))

    with pytest.raises(DBAPIError, match="injected booking failure"):
        InvoiceInventoryBookingService(factory).apply_line(
            InvoiceInventoryLine("pg-invoice-rollback", "position-1", variant_id, 2)
        )

    location = InventoryRepository(factory).get_or_create_location(code="MAIN", name="Hauptlager")
    stock = InventoryRepository(factory).get_stock(variant_id, location.id)
    assert stock is not None and stock.on_hand == 10
    with factory() as session:
        assert session.query(InventoryDocumentBooking).filter_by(
            document_id="pg-invoice-rollback"
        ).count() == 0
        assert session.query(InventoryMovement).filter_by(
            external_reference="pg-invoice-rollback:position-1"
        ).count() == 0


def test_parallel_claim_stores_across_postgres_connections_have_one_winner(
    postgres_factory: sessionmaker[Session],
) -> None:
    factory = postgres_factory
    stores = [
        InvoiceOperationClaimStore(SettingKvRepository(factory)),
        InvoiceOperationClaimStore(SettingKvRepository(factory)),
    ]
    barrier = threading.Barrier(2)

    def acquire(store: InvoiceOperationClaimStore) -> OperationClaim:
        barrier.wait(timeout=10)
        return store.acquire("pg-invoice-claim", "invoice_mail")

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = [future.result(timeout=30) for future in [pool.submit(acquire, store) for store in stores]]

    assert sum(claim.acquired for claim in claims) == 1
    assert {claim.state for claim in claims} == {"running"}
    assert len({claim.operation_id for claim in claims}) == 1
