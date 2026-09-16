"""Tests for the Inventory V2 ledger repository (PR13, shadow mode)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository, NegativeStockError


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def repo(session_factory: sessionmaker[Session]) -> InventoryRepository:
    return InventoryRepository(session_factory)


@pytest.fixture
def variant_id(session_factory: sessionmaker[Session]) -> uuid.UUID:
    product_repo = ProductHubRepository(session_factory)
    _product, variant = product_repo.create_product(sku="XW-5000", name="Ledger Produkt")
    return variant.id


def test_get_or_create_location_is_idempotent(repo: InventoryRepository) -> None:
    first = repo.get_or_create_location(code="MAIN", name="Hauptlager")
    second = repo.get_or_create_location(code="MAIN", name="Hauptlager (anderer Name)")
    assert first.id == second.id
    assert first.name == "Hauptlager"  # first write wins, not overwritten


def test_record_movement_creates_stock_row_and_ledger_entry(
    repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = repo.get_or_create_location(code="MAIN", name="Hauptlager")

    movement = repo.record_movement(
        variant_id=variant_id,
        location_id=location.id,
        delta=10,
        reason="import_baseline",
        source="test",
        idempotency_key="key-1",
    )

    assert movement.on_hand_after == 10
    stock = repo.get_stock(variant_id, location.id)
    assert stock is not None
    assert stock.on_hand == 10
    assert stock.version == 2  # created at 1, bumped on the movement


def test_record_movement_is_idempotent_on_key(
    repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = repo.get_or_create_location(code="MAIN", name="Hauptlager")
    first = repo.record_movement(
        variant_id=variant_id, location_id=location.id, delta=5,
        reason="sale", source="test", idempotency_key="dup-key",
    )
    second = repo.record_movement(
        variant_id=variant_id, location_id=location.id, delta=5,
        reason="sale", source="test", idempotency_key="dup-key",
    )

    assert first.id == second.id
    stock = repo.get_stock(variant_id, location.id)
    assert stock is not None
    assert stock.on_hand == 5  # delta applied once, not twice


def test_record_movement_rejects_negative_stock(
    repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = repo.get_or_create_location(code="MAIN", name="Hauptlager")
    repo.record_movement(
        variant_id=variant_id, location_id=location.id, delta=3,
        reason="import_baseline", source="test", idempotency_key="k1",
    )
    with pytest.raises(NegativeStockError):
        repo.record_movement(
            variant_id=variant_id, location_id=location.id, delta=-5,
            reason="sale", source="test", idempotency_key="k2",
        )
    # the rejected movement must not have been applied
    stock = repo.get_stock(variant_id, location.id)
    assert stock is not None
    assert stock.on_hand == 3


def test_set_stock_thresholds(repo: InventoryRepository, variant_id: uuid.UUID) -> None:
    location = repo.get_or_create_location(code="MAIN", name="Hauptlager")
    stock = repo.set_stock_thresholds(variant_id, location.id, reorder_point=5, target_stock=20)
    assert stock.reorder_point == 5
    assert stock.target_stock == 20

    updated = repo.set_stock_thresholds(variant_id, location.id, reorder_point=8)
    assert updated.reorder_point == 8
    assert updated.target_stock == 20  # untouched field preserved


def test_list_movements_orders_newest_first(
    repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = repo.get_or_create_location(code="MAIN", name="Hauptlager")
    repo.record_movement(
        variant_id=variant_id, location_id=location.id, delta=1,
        reason="import_baseline", source="t", idempotency_key="m1",
    )
    repo.record_movement(
        variant_id=variant_id, location_id=location.id, delta=1,
        reason="sale", source="t", idempotency_key="m2",
    )
    movements = repo.list_movements(variant_id, location.id)
    assert [m.idempotency_key for m in movements] == ["m2", "m1"]


def test_open_or_update_alert_dedupes_while_open(
    repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = repo.get_or_create_location(code="MAIN", name="Hauptlager")
    first = repo.open_or_update_alert(
        variant_id=variant_id, location_id=location.id, alert_type="low_stock",
        threshold=5, observed_stock=3,
    )
    second = repo.open_or_update_alert(
        variant_id=variant_id, location_id=location.id, alert_type="low_stock",
        threshold=5, observed_stock=2,
    )
    assert first.id == second.id
    assert repo.get_alert(first.id).observed_stock == 2  # type: ignore[union-attr]


def test_resolve_alert_allows_a_new_one_to_open(
    repo: InventoryRepository, variant_id: uuid.UUID
) -> None:
    location = repo.get_or_create_location(code="MAIN", name="Hauptlager")
    first = repo.open_or_update_alert(
        variant_id=variant_id, location_id=location.id, alert_type="low_stock",
        threshold=5, observed_stock=3,
    )
    repo.resolve_alert(first.id)

    second = repo.open_or_update_alert(
        variant_id=variant_id, location_id=location.id, alert_type="low_stock",
        threshold=5, observed_stock=1,
    )
    assert second.id != first.id
    assert [a.id for a in repo.list_open_alerts()] == [second.id]


def test_resolve_unknown_alert_raises(repo: InventoryRepository) -> None:
    with pytest.raises(KeyError):
        repo.resolve_alert(uuid.uuid4())
