from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import Product, ProductVariant
from xw_office.models.product_hub_inventory import InventoryMovement
from xw_office.models.settings_kv import SettingKV
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.inventory_count import InventoryCountService


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        product = Product(
            id=uuid.uuid4(), sku="XW-COUNT", name="Zählstück", slug="zaehlstueck",
            status="live", product_type="physical", active=True, attributes={},
        )
        session.add(product)
        session.flush()
        variant = ProductVariant(
            id=uuid.uuid4(), product_id=product.id, sku="XW-COUNT", name="Zählstück",
            active=True, stock_enabled=True, attributes={"article_kind": "pod"}, option_values={},
        )
        session.add(variant)
        session.commit()
        return factory, variant.id


def test_count_confirm_applies_one_recount_and_is_idempotent() -> None:
    factory, variant_id = _factory()
    InventoryV2Service(factory).record_movement(
        variant_id=variant_id, delta=20, reason="import_baseline", source="test",
        idempotency_key="count-baseline",
    )
    service = InventoryCountService(factory)
    count = service.start()
    assert len(count.lines) == 1
    service.record_count(count_id=count.id, line_id=count.lines[0].id, counted_quantity=17)
    confirmed = service.confirm(count_id=count.id, actor="tester")
    assert confirmed.status == "confirmed"
    assert confirmed.lines[0].difference == -3
    assert len(InventoryV2Service(factory)._inventory.list_movements(variant_id, InventoryV2Service(factory)._inventory.get_or_create_location(code="MAIN", name="Hauptlager").id)) == 2
    repeated = service.confirm(count_id=count.id, actor="tester")
    assert repeated.status == "confirmed"
    with factory() as session:
        assert session.query(InventoryMovement).filter_by(reason="recount").count() == 1
        setting = session.get(SettingKV, "product_hub.sevdesk_invoice_feed_start.v1")
        assert setting is not None


def test_count_requires_all_lines_and_excludes_digital_variants() -> None:
    factory, variant_id = _factory()
    with factory() as session:
        product = Product(id=uuid.uuid4(), sku="DIGITAL", name="Digital", slug="digital", status="live", product_type="digital", active=True, attributes={})
        session.add(product)
        session.flush()
        session.add(ProductVariant(id=uuid.uuid4(), product_id=product.id, sku="DIGITAL", name="Digital", active=True, stock_enabled=False, attributes={}, option_values={}))
        session.commit()
    service = InventoryCountService(factory)
    count = service.start()
    assert all(line.variant_id == variant_id for line in count.lines)
    try:
        service.confirm(count_id=count.id)
    except ValueError as exc:
        assert "gezählt" in str(exc)
    else:
        raise AssertionError("unvollständige Inventur muss abgelehnt werden")
