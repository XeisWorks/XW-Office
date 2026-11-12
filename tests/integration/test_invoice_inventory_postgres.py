"""Opt-in PostgreSQL race tests for invoice inventory bookings.

Set ``XW_TEST_POSTGRES_URL`` to an isolated, disposable PostgreSQL database.
The test creates and drops a uniquely named schema; it never touches the public
schema or the application's ``DATABASE_URL``.
"""
from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
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
from xw_office.services.sevdesk.part_client import PartClient
from xw_office.services.invoice_processing.operation_claims import (
    InvoiceOperationClaimStore,
    OperationClaim,
)
from xw_office.services.products.catalog import Product, ProductCatalogService
from xw_office.services.products.print_decision import PieceBlock, PrintDecisionEngine
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


def _postgres_process_claim(
    database_url: str,
    invoice_id: str,
    operation: str,
    barrier: object,
    result_queue: object,
) -> None:
    """Acquire one durable claim using a fresh OS process and DB connection."""
    engine = create_engine(database_url, future=True, pool_size=1, max_overflow=0)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    try:
        barrier.wait(timeout=20)  # type: ignore[attr-defined]
        claim = InvoiceOperationClaimStore(SettingKvRepository(factory)).acquire(
            invoice_id, operation
        )
        result_queue.put((claim.acquired, claim.operation_id, claim.state))  # type: ignore[attr-defined]
    finally:
        engine.dispose()


def _postgres_process_claim_then_abort(database_url: str, invoice_id: str, operation: str) -> None:
    """Commit a running claim, then emulate a hard process loss before finish."""
    engine = create_engine(database_url, future=True, pool_size=1, max_overflow=0)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    InvoiceOperationClaimStore(SettingKvRepository(factory)).acquire(invoice_id, operation)
    os._exit(73)  # noqa: SLF001 - intentional uncatchable process-abort simulation.


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


def test_parallel_claims_from_separate_postgres_processes_have_one_winner(
    postgres_factory: sessionmaker[Session],
) -> None:
    bind = postgres_factory.kw["bind"]
    assert isinstance(bind, Engine)
    database_url = bind.url.render_as_string(hide_password=False)
    context = get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    invoice_id = f"pg-process-claim-{uuid.uuid4()}"
    processes = [
        context.Process(
            target=_postgres_process_claim,
            args=(database_url, invoice_id, "invoice_mail", barrier, results),
        )
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=45)
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        assert [process.exitcode for process in processes] == [0, 0]
        claims = [results.get(timeout=5), results.get(timeout=5)]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()

    assert sum(bool(claim[0]) for claim in claims) == 1
    assert {claim[2] for claim in claims} == {"running"}
    assert len({claim[1] for claim in claims}) == 1


def test_running_claim_survives_postgres_process_abort_and_requires_reconciliation(
    postgres_factory: sessionmaker[Session],
) -> None:
    bind = postgres_factory.kw["bind"]
    assert isinstance(bind, Engine)
    database_url = bind.url.render_as_string(hide_password=False)
    context = get_context("spawn")
    invoice_id = f"pg-aborted-claim-{uuid.uuid4()}"
    operation = "invoice_finalize"
    process = context.Process(
        target=_postgres_process_claim_then_abort,
        args=(database_url, invoice_id, operation),
    )
    process.start()
    process.join(timeout=45)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    assert process.exitcode == 73

    store = InvoiceOperationClaimStore(SettingKvRepository(postgres_factory))
    open_claims = [claim for claim in store.list_open() if claim.invoice_id == invoice_id]
    assert len(open_claims) == 1
    orphaned = open_claims[0]
    assert orphaned.operation == operation
    assert orphaned.state == "running"
    competing = InvoiceOperationClaimStore(SettingKvRepository(postgres_factory)).acquire(
        invoice_id, operation
    )
    assert not competing.acquired
    assert competing.state == "running"

    reconciled = store.reconcile_open(
        invoice_id,
        operation,
        orphaned.operation_id,
        "failed",
        reconciled_by="postgres-process-test",
        evidence="isolated child process exited before side effect",
        expected_state="running",
        no_active_processes_confirmed=True,
    )
    assert reconciled.state == "failed"
    retried = InvoiceOperationClaimStore(SettingKvRepository(postgres_factory)).acquire(
        invoice_id, operation
    )
    assert retried.acquired
    assert retried.operation_id == orphaned.operation_id


def test_parallel_part_stock_updates_are_serialized_by_postgres_advisory_lock(
    postgres_factory: sessionmaker[Session],
) -> None:
    factory = postgres_factory
    first_read = threading.Event()
    release_first_read = threading.Event()
    second_read = threading.Event()
    guard = threading.Lock()
    state_guard = threading.Lock()
    state = {"reads": 0, "stock": 10}

    class SharedPartClient:
        def get_part_stock(self, _part_id: str) -> int:
            with guard:
                state["reads"] += 1
                read_number = state["reads"]
            if read_number == 1:
                first_read.set()
                if not release_first_read.wait(timeout=10):
                    raise TimeoutError("first stock read was not released")
            else:
                second_read.set()
            with state_guard:
                return state["stock"]

        def set_part_stock(self, _part_id: str, stock: int) -> None:
            with state_guard:
                state["stock"] = stock

        def find_part_by_sku(self, _sku: str) -> None:
            return None

    repository = SettingKvRepository(factory)
    part_client = SharedPartClient()
    engines = [
        PrintDecisionEngine(
            ProductCatalogService(), cast(PartClient, part_client), settings_repo=repository
        ),
        PrintDecisionEngine(
            ProductCatalogService(), cast(PartClient, part_client), settings_repo=repository
        ),
    ]
    piece = PieceBlock(
        sku="XW-PG-PART",
        name="PostgreSQL part stock test",
        qty_needed=1,
        product=Product(
            id="product-pg-part",
            sku="XW-PG-PART",
            name="PostgreSQL part stock test",
            sevdesk_part_id="pg-part-1",
        ),
    )
    second_started = threading.Event()

    def update(engine: PrintDecisionEngine, *, second: bool = False) -> int:
        if second:
            second_started.set()
        return engine.record_print_and_update_sevdesk(
            piece, qty_printed=1, invoice_ref="pg-part-lock"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(update, engines[0])
        assert first_read.wait(timeout=5)
        second_future = pool.submit(update, engines[1], second=True)
        try:
            assert second_started.wait(timeout=5)
            assert not second_read.wait(timeout=0.2)
        finally:
            release_first_read.set()
        assert first_future.result(timeout=30) == 11
        assert second_future.result(timeout=30) == 12

    assert state["stock"] == 12
    assert state["reads"] == 2
