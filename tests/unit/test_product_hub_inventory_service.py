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
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.product_hub.inventory import (
    InventoryV2Service,
    LegacyInventoryShadowBridge,
)


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


def test_cutover_readiness_exposes_real_evidence_and_remaining_gates(
    session_factory: sessionmaker[Session], variant_id: uuid.UUID
) -> None:
    service = InventoryV2Service(session_factory, shadow_enabled=True)
    service.record_movement(
        variant_id=variant_id, delta=8, reason="import_baseline",
        source="test", idempotency_key="cutover-readiness-1",
    )

    readiness = service.cutover_readiness()
    checks = {check.code: check for check in readiness.checks}
    assert readiness.master_enabled is False
    assert readiness.shadow_enabled is True
    assert readiness.eligible is False
    assert checks["shadow_mode"].state == "ready"
    assert checks["ledger_evidence"].state == "ready"
    assert checks["sevdesk_drift"].state == "ready"
    assert checks["legacy_mutation_paths"].state == "blocked"
    assert checks["channel_projections"].state == "blocked"
    assert checks["operational_signoff"].state == "manual"


def test_legacy_baseline_requires_shadow_mode_and_never_rebases_a_variant(
    session_factory: sessionmaker[Session],
    product_repo: ProductHubRepository,
) -> None:
    product, variant = product_repo.create_product(sku="XW-BASELINE", name="Baseline Produkt")
    del product
    settings = SettingKvRepository(session_factory)
    settings.set_value_json("inventory.stock_levels", '{"XW-BASELINE": 7, "UNKNOWN": 3}')

    disabled = InventoryV2Service(session_factory, shadow_enabled=False)
    preview = disabled.legacy_baseline_preview()
    assert [item.status for item in preview.items] == ["missing_hub_variant", "ready"]
    with pytest.raises(ValueError, match="Shadow Mode"):
        disabled.apply_legacy_baseline(expected_source_hash=preview.source_hash)

    service = InventoryV2Service(session_factory, shadow_enabled=True)
    preview = service.legacy_baseline_preview()
    applied = service.apply_legacy_baseline(expected_source_hash=preview.source_hash)
    assert applied.applied_skus == ["XW-BASELINE"]
    assert [item.sku for item in applied.blocked_items] == ["UNKNOWN"]
    location = InventoryRepository(session_factory).get_location_by_code("MAIN")
    assert location is not None
    stock = InventoryRepository(session_factory).get_stock(variant.id, location.id)
    assert stock is not None and stock.on_hand == 7
    assert settings.get_value_json("inventory.stock_levels") == '{"XW-BASELINE": 7, "UNKNOWN": 3}'
    refreshed = service.legacy_baseline_preview()
    assert next(item for item in refreshed.items if item.sku == "XW-BASELINE").status == "ledger_already_initialized"


def test_legacy_shadow_bridge_mirrors_only_baselined_active_variants(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    _product, variant = product_repo.create_product(sku="XW-MIRROR", name="Mirror Produkt")
    unseeded_product, _unseeded_variant = product_repo.create_product(
        sku="XW-UNSEEDED", name="Unseeded Produkt"
    )
    del unseeded_product
    service = InventoryV2Service(session_factory)
    service.record_movement(
        variant_id=variant.id, delta=10, reason="import_baseline",
        source="test", idempotency_key="mirror-baseline",
    )
    bridge = LegacyInventoryShadowBridge(session_factory)

    mirrored = bridge.mirror_absolute_stock(
        sku="XW-MIRROR", new_stock=6, source="desktop-test"
    )
    assert mirrored.status == "mirrored"
    location = InventoryRepository(session_factory).get_location_by_code("MAIN")
    assert location is not None
    stock = InventoryRepository(session_factory).get_stock(variant.id, location.id)
    assert stock is not None and stock.on_hand == 6
    assert bridge.mirror_absolute_stock(
        sku="XW-MIRROR", new_stock=6, source="desktop-test"
    ).status == "already_in_sync"
    printed = bridge.mirror_stock_movement(
        sku="XW-MIRROR", delta=3, reason="print_run", source="desktop-test"
    )
    sold = bridge.mirror_stock_movement(
        sku="XW-MIRROR", delta=-2, reason="sale", source="desktop-test"
    )
    assert printed.status == "mirrored"
    assert sold.status == "mirrored"
    stock = InventoryRepository(session_factory).get_stock(variant.id, location.id)
    assert stock is not None and stock.on_hand == 7
    assert bridge.mirror_absolute_stock(
        sku="XW-UNSEEDED", new_stock=2, source="desktop-test"
    ).status == "baseline_required"


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
