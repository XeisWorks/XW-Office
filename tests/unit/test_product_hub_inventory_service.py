"""Tests for the Inventory V2 service: alert crossing, shadow reconcile, summary (PR13/PR14)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub_sync import OutboxEvent
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.inventory import InventoryV2Service


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def product_repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


@pytest.fixture
def inventory_repo(session_factory: sessionmaker[Session]) -> InventoryRepository:
    return InventoryRepository(session_factory)


@pytest.fixture
def service(session_factory: sessionmaker[Session]) -> InventoryV2Service:
    return InventoryV2Service(session_factory, public_base_url="https://studio.example")


@pytest.fixture
def variant_id(product_repo: ProductHubRepository) -> uuid.UUID:
    _product, variant = product_repo.create_product(sku="XW-6000", name="Alert Produkt")
    return variant.id


def _outbox_events(session_factory: sessionmaker[Session]) -> list[OutboxEvent]:
    with session_factory() as session:
        return list(session.query(OutboxEvent).all())


# -- movement recording + alert crossing --------------------------------------------


def test_record_movement_applies_delta(
    service: InventoryV2Service, inventory_repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    result = service.record_movement(
        variant_id=variant_id, delta=10, reason="import_baseline",
        source="test", idempotency_key="rm-1",
    )
    assert result.movement.on_hand_after == 10
    assert result.alert_opened is None  # no threshold set yet, nothing to cross


def test_record_movement_crossing_below_threshold_opens_low_stock_alert(
    service: InventoryV2Service, inventory_repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = inventory_repo.get_or_create_location(code="MAIN", name="Hauptlager")
    inventory_repo.set_stock_thresholds(variant_id, location.id, reorder_point=5)

    service.record_movement(
        variant_id=variant_id, delta=10, reason="import_baseline",
        source="test", idempotency_key="rm-2a",
    )
    result = service.record_movement(
        variant_id=variant_id, delta=-6, reason="sale", source="test", idempotency_key="rm-2b",
    )  # 10 -> 4, crosses reorder_point=5

    assert result.alert_opened is not None
    assert result.alert_opened.type == "low_stock"


def test_record_movement_crossing_to_zero_opens_out_of_stock_alert(
    service: InventoryV2Service, inventory_repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = inventory_repo.get_or_create_location(code="MAIN", name="Hauptlager")
    inventory_repo.set_stock_thresholds(variant_id, location.id, reorder_point=5)

    service.record_movement(
        variant_id=variant_id, delta=10, reason="import_baseline",
        source="test", idempotency_key="rm-3a",
    )
    result = service.record_movement(
        variant_id=variant_id, delta=-10, reason="sale", source="test", idempotency_key="rm-3b",
    )

    assert result.alert_opened is not None
    assert result.alert_opened.type == "out_of_stock"


def test_record_movement_does_not_reopen_already_open_alert(
    service: InventoryV2Service, inventory_repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = inventory_repo.get_or_create_location(code="MAIN", name="Hauptlager")
    inventory_repo.set_stock_thresholds(variant_id, location.id, reorder_point=5)

    service.record_movement(
        variant_id=variant_id, delta=10, reason="import_baseline",
        source="test", idempotency_key="rm-4a",
    )
    first = service.record_movement(
        variant_id=variant_id, delta=-6, reason="sale", source="test", idempotency_key="rm-4b",
    )
    second = service.record_movement(
        variant_id=variant_id, delta=-1, reason="sale", source="test", idempotency_key="rm-4c",
    )

    assert first.alert_opened is not None
    assert second.alert_opened is None  # still the same open alert, not a new one
    assert len(inventory_repo.list_open_alerts()) == 1


def test_record_movement_resolves_alert_once_back_above_threshold(
    service: InventoryV2Service, inventory_repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = inventory_repo.get_or_create_location(code="MAIN", name="Hauptlager")
    inventory_repo.set_stock_thresholds(variant_id, location.id, reorder_point=5)

    service.record_movement(
        variant_id=variant_id, delta=10, reason="import_baseline",
        source="test", idempotency_key="rm-5a",
    )
    service.record_movement(
        variant_id=variant_id, delta=-6, reason="sale", source="test", idempotency_key="rm-5b",
    )
    assert len(inventory_repo.list_open_alerts()) == 1

    service.record_movement(
        variant_id=variant_id, delta=10, reason="return", source="test", idempotency_key="rm-5c",
    )
    assert inventory_repo.list_open_alerts() == []


def test_alert_opening_writes_xw_flow_task_intent_outbox_event(
    service: InventoryV2Service,
    inventory_repo: InventoryRepository,
    session_factory: sessionmaker[Session],
    variant_id: uuid.UUID,
) -> None:
    location = inventory_repo.get_or_create_location(code="MAIN", name="Hauptlager")
    inventory_repo.set_stock_thresholds(variant_id, location.id, reorder_point=5)

    service.record_movement(
        variant_id=variant_id, delta=10, reason="import_baseline",
        source="test", idempotency_key="rm-6a",
    )
    result = service.record_movement(
        variant_id=variant_id, delta=-6, reason="sale", source="test", idempotency_key="rm-6b",
    )
    assert result.alert_opened is not None

    events = _outbox_events(session_factory)
    matching = [e for e in events if e.event_type == "inventory_alert.opened"]
    assert len(matching) == 1
    payload = matching[0].payload
    assert payload["title"] == "Nachdruck: XW-6000 – Alert Produkt"
    assert payload["planning_mode"] == "PIPELINE"
    assert payload["external_entity_type"] == "inventory_alert"
    assert payload["external_entity_id"] == str(result.alert_opened.id)
    assert payload["external_deep_link"].startswith("https://studio.example/app/products/")


# -- shadow reconcile -----------------------------------------------------------------


def test_reconcile_no_drift_when_equal(
    service: InventoryV2Service, variant_id: uuid.UUID
) -> None:
    service.record_movement(
        variant_id=variant_id, delta=7, reason="import_baseline",
        source="test", idempotency_key="rc-1",
    )
    drift = service.reconcile_variant_stock(variant_id, sevdesk_on_hand=7)
    assert drift is False


def test_reconcile_creates_sync_conflict_on_drift(
    service: InventoryV2Service, session_factory: sessionmaker[Session], variant_id: uuid.UUID
) -> None:
    service.record_movement(
        variant_id=variant_id, delta=7, reason="import_baseline",
        source="test", idempotency_key="rc-2",
    )
    drift = service.reconcile_variant_stock(variant_id, sevdesk_on_hand=3)
    assert drift is True

    sync_repo = SyncRepository(session_factory)
    conflicts = sync_repo.list_open_sync_conflicts(channel="sevdesk")
    assert len(conflicts) == 1
    assert conflicts[0].field_name == "on_hand"
    assert conflicts[0].hub_value == "7"
    assert conflicts[0].external_value == "3"


def test_reconcile_does_not_duplicate_open_conflict(
    service: InventoryV2Service, session_factory: sessionmaker[Session], variant_id: uuid.UUID
) -> None:
    service.record_movement(
        variant_id=variant_id, delta=7, reason="import_baseline",
        source="test", idempotency_key="rc-3",
    )
    service.reconcile_variant_stock(variant_id, sevdesk_on_hand=3)
    service.reconcile_variant_stock(variant_id, sevdesk_on_hand=2)  # still drifting

    sync_repo = SyncRepository(session_factory)
    assert len(sync_repo.list_open_sync_conflicts(channel="sevdesk")) == 1


# -- summary --------------------------------------------------------------------------


def test_compute_summary_counts_alerts_and_products(
    service: InventoryV2Service,
    inventory_repo: InventoryRepository,
    product_repo: ProductHubRepository,
) -> None:
    _product, variant = product_repo.create_product(
        sku="XW-6001", name="Physisches Produkt", status="live", product_type="physical"
    )
    location = inventory_repo.get_or_create_location(code="MAIN", name="Hauptlager")
    inventory_repo.set_stock_thresholds(variant.id, location.id, reorder_point=5)
    service.record_movement(
        variant_id=variant.id, delta=10, reason="import_baseline",
        source="test", idempotency_key="sum-1",
    )
    service.record_movement(
        variant_id=variant.id, delta=-10, reason="sale", source="test", idempotency_key="sum-2",
    )

    summary = service.compute_summary()
    assert summary.physical_products == 1
    assert summary.out_of_stock == 1
    assert summary.open_reprint_alerts == 1
