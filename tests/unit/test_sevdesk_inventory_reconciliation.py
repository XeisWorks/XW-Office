"""Tests for read-only Hub/sevDesk stock reconciliation."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import ProductVariant
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.sevdesk_inventory_reconciliation import (
    SevdeskInventoryReconciliationService,
)


class FakePartClient:
    def __init__(self, stocks: dict[str, int | Exception]) -> None:
        self.stocks = stocks
        self.requests: list[tuple[str, bool]] = []

    def get_part_stock(self, part_id: str, *, strict: bool = False) -> int:
        self.requests.append((part_id, strict))
        value = self.stocks[part_id]
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _live_product_with_part(
    factory: sessionmaker[Session], *, sku: str = "XW-RECON", part_id: str = "part-1"
) -> tuple[uuid.UUID, uuid.UUID]:
    products = ProductHubRepository(factory)
    product, variant = products.create_product(
        sku=sku, name="Reconciliation product", status="live", product_type="physical"
    )
    products.update_product(
        product.id, expected_row_version=product.row_version, sevdesk_part_id=part_id
    )
    return product.id, variant.id


def test_reconciliation_creates_and_then_resolves_stock_drift(
    session_factory: sessionmaker[Session],
) -> None:
    _product_id, variant_id = _live_product_with_part(session_factory)
    inventory = InventoryV2Service(session_factory, shadow_enabled=True)
    inventory.record_movement(
        variant_id=variant_id,
        delta=7,
        reason="import_baseline",
        source="test",
        idempotency_key="reconcile-seed",
    )
    part_client = FakePartClient({"part-1": 4})
    service = SevdeskInventoryReconciliationService(
        session_factory, part_client, shadow_enabled=True
    )

    drift = service.run()

    assert drift.compared == 1
    assert drift.drifts == 1
    assert drift.items[0].state == "drift"
    assert part_client.requests == [("part-1", True)]
    assert len(SyncRepository(session_factory).list_open_sync_conflicts(channel="sevdesk")) == 1

    part_client.stocks["part-1"] = 7
    equal = service.run()

    assert equal.compared == 1
    assert equal.drifts == 0
    assert equal.items[0].state == "equal"
    assert SyncRepository(session_factory).list_open_sync_conflicts(channel="sevdesk") == []


def test_reconciliation_skips_ambiguous_parent_part_mapping(
    session_factory: sessionmaker[Session],
) -> None:
    product_id, _variant_id = _live_product_with_part(session_factory)
    with session_factory.begin() as session:
        session.add(
            ProductVariant(
                id=uuid.uuid4(),
                product_id=product_id,
                sku="XW-RECON-SECOND",
                name="Second stock variant",
                active=True,
                stock_enabled=True,
                is_default=False,
                option_values={},
                attributes={},
            )
        )
    part_client = FakePartClient({"part-1": 7})

    result = SevdeskInventoryReconciliationService(
        session_factory, part_client, shadow_enabled=True
    ).run()

    assert result.compared == 0
    assert result.skipped == 1
    assert result.items[0].detail == "Mehrere Lager-Varianten teilen einen sevDesk-Part"
    assert part_client.requests == []


def test_reconciliation_reports_part_read_error_without_creating_false_drift(
    session_factory: sessionmaker[Session],
) -> None:
    _product_id, variant_id = _live_product_with_part(session_factory)
    InventoryV2Service(session_factory, shadow_enabled=True).record_movement(
        variant_id=variant_id,
        delta=3,
        reason="import_baseline",
        source="test",
        idempotency_key="reconcile-error-seed",
    )

    result = SevdeskInventoryReconciliationService(
        session_factory,
        FakePartClient({"part-1": RuntimeError("sevDesk unavailable")}),
        shadow_enabled=True,
    ).run()

    assert result.errors == 1
    assert result.drifts == 0
    assert SyncRepository(session_factory).list_open_sync_conflicts(channel="sevdesk") == []


def test_reconciliation_requires_shadow_mode(session_factory: sessionmaker[Session]) -> None:
    _live_product_with_part(session_factory)
    service = SevdeskInventoryReconciliationService(
        session_factory, FakePartClient({"part-1": 0}), shadow_enabled=False
    )

    with pytest.raises(RuntimeError, match="Shadow Mode"):
        service.run()
