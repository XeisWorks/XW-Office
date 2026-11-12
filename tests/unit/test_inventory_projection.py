"""Tests for canonical Product-Hub stock projections."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.inventory_projection import InventoryProjectionService


class _FakeSevdesk:
    def __init__(self, stocks: dict[str, int]) -> None:
        self.stocks = dict(stocks)
        self.writes: list[tuple[str, int]] = []

    def get_part_stock(self, part_id: str, *, strict: bool = False) -> int:
        return self.stocks[part_id]

    def set_part_stock(self, part_id: str, new_stock: int) -> None:
        self.writes.append((part_id, new_stock))
        self.stocks[part_id] = int(new_stock)


class _FakeWix:
    def __init__(self, items: dict[str, list[dict[str, object]]]) -> None:
        self.items = items
        self.writes: list[tuple[str, str, int]] = []

    def query_inventory(self, product_id: str) -> list[dict[str, object]]:
        return [dict(item) for item in self.items.get(product_id, [])]

    def update_inventory_item(
        self, inventory_item_id: str, *, revision: str, quantity: int, reason: str = "MANUAL"
    ) -> dict[str, object]:
        self.writes.append((inventory_item_id, revision, quantity))
        for items in self.items.values():
            for item in items:
                if str(item.get("id")) == inventory_item_id:
                    item["quantity"] = quantity
                    item["revision"] = str(int(revision) + 1)
                    return dict(item)
        raise KeyError(inventory_item_id)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _seed(factory: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    repo = ProductHubRepository(factory)
    product, variant = repo.create_product(
        sku="XW-PROJ", name="Projection", status="live", product_type="physical"
    )
    repo.create_channel_mapping(
        channel="sevdesk", entity_type="product", internal_entity_id=product.id, external_id="part-1"
    )
    repo.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id="wix-product-1"
    )
    InventoryV2Service(factory).record_movement(
        variant_id=variant.id,
        delta=12,
        reason="import_baseline",
        source="test",
        idempotency_key="projection-seed",
    )
    return product.id, variant.id


def test_dry_run_is_read_only_and_write_run_is_idempotent() -> None:
    factory = _factory()
    _product_id, _variant_id = _seed(factory)
    sevdesk = _FakeSevdesk({"part-1": 4})
    wix = _FakeWix(
        {"wix-product-1": [{"id": "wix-inv-1", "productId": "wix-product-1", "quantity": 2,
                              "trackQuantity": True, "revision": "3"}]}
    )
    service = InventoryProjectionService(
        factory, sevdesk=sevdesk, wix=wix, write_enabled=lambda: True
    )

    preview = service.run(dry_run=True)
    assert preview.would_project == 2
    assert sevdesk.writes == []
    assert wix.writes == []

    projected = service.run(dry_run=False)
    assert projected.projected == 2
    assert sevdesk.writes == [("part-1", 12)]
    assert wix.writes == [("wix-inv-1", "3", 12)]

    repeat = service.run(dry_run=False)
    assert repeat.equal == 2
    assert len(sevdesk.writes) == 1
    assert len(wix.writes) == 1


def test_external_change_after_projection_becomes_conflict() -> None:
    factory = _factory()
    _seed(factory)
    sevdesk = _FakeSevdesk({"part-1": 4})
    service = InventoryProjectionService(factory, sevdesk=sevdesk, write_enabled=lambda: True)

    assert service.run(dry_run=False).projected == 1
    sevdesk.stocks["part-1"] = 99

    result = service.run(dry_run=False)
    assert result.conflicts == 1
    assert sevdesk.writes == [("part-1", 12)]


def test_sevdesk_projection_holds_shared_part_stock_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _factory()
    _seed(factory)
    lock_state = {"active": False}

    @contextmanager
    def tracked_lock(_repository: SettingKvRepository, key: str) -> Iterator[None]:
        assert key == "sevdesk-part-stock:part-1"
        assert not lock_state["active"]
        lock_state["active"] = True
        try:
            yield
        finally:
            lock_state["active"] = False

    class LockedSevdesk(_FakeSevdesk):
        def get_part_stock(self, part_id: str, *, strict: bool = False) -> int:
            assert lock_state["active"]
            return super().get_part_stock(part_id, strict=strict)

        def set_part_stock(self, part_id: str, new_stock: int) -> None:
            assert lock_state["active"]
            super().set_part_stock(part_id, new_stock)

    monkeypatch.setattr(SettingKvRepository, "advisory_lock", tracked_lock)
    sevdesk = LockedSevdesk({"part-1": 4})

    result = InventoryProjectionService(
        factory, sevdesk=sevdesk, write_enabled=lambda: True
    ).run(dry_run=False)

    assert result.projected == 1
    assert not lock_state["active"]
    assert sevdesk.writes == [("part-1", 12)]


def test_write_gate_prevents_provider_calls() -> None:
    factory = _factory()
    _seed(factory)
    sevdesk = _FakeSevdesk({"part-1": 4})
    result = InventoryProjectionService(
        factory, sevdesk=sevdesk, write_enabled=lambda: False
    ).run(dry_run=False)

    assert result.items[0].state == "disabled"
    assert sevdesk.writes == []


def test_equal_dry_run_does_not_archive_or_resolve_conflicts() -> None:
    factory = _factory()
    _product_id, variant_id = _seed(factory)
    sync = SyncRepository(factory)
    conflict = sync.create_sync_conflict(
        channel="sevdesk", entity_type="inventory_stock", internal_entity_id=variant_id,
        field_name="on_hand", hub_value=12, external_value=4,
    )
    sevdesk = _FakeSevdesk({"part-1": 12})

    result = InventoryProjectionService(factory, sevdesk=sevdesk).run(dry_run=True)

    assert result.equal == 1
    assert sync.get_latest_external_payload(
        channel="sevdesk", entity_type="inventory_stock", external_id="part-1"
    ) is None
    current_conflict = sync.get_sync_conflict(conflict.id)
    assert current_conflict is not None
    assert current_conflict.resolved_at is None


def test_conflicting_dry_run_does_not_persist_a_conflict() -> None:
    factory = _factory()
    _seed(factory)
    sevdesk = _FakeSevdesk({"part-1": 4})
    service = InventoryProjectionService(factory, sevdesk=sevdesk, write_enabled=lambda: True)

    assert service.run(dry_run=False).projected == 1
    sevdesk.stocks["part-1"] = 99

    preview = InventoryProjectionService(factory, sevdesk=sevdesk).run(dry_run=True)

    assert preview.conflicts == 1
    assert SyncRepository(factory).list_open_sync_conflicts(channel="sevdesk") == []

