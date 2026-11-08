from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.settings_kv import SettingKV
from xw_office.services.product_hub.inventory_external_mirror import InventoryExternalMirrorService


def test_external_mirror_is_idempotent_and_updates_legacy_snapshots() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                SettingKV(key="inventory.stock_levels", value_json='{"SKU-1": 5}'),
                SettingKV(key="inventory.products", value_json='[{"sku":"SKU-1","on_hand":5}]'),
            ]
        )
        session.commit()
    service = InventoryExternalMirrorService(factory)
    first = service.apply(sku="SKU-1", delta=-2, idempotency_key="invoice:1", external_reference="1:1")
    repeated = service.apply(sku="SKU-1", delta=-2, idempotency_key="invoice:1", external_reference="1:1")
    assert first.status == "mirrored"
    assert first.previous_stock == 5 and first.new_stock == 3
    assert repeated.status == "already_applied"
    with factory() as session:
        assert session.get(SettingKV, "inventory.stock_levels").value_json == '{"SKU-1": 3}'
        assert '"on_hand": 3' in session.get(SettingKV, "inventory.products").value_json


def test_external_mirror_reports_shortage_without_negative_stock() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        session.add(SettingKV(key="inventory.stock_levels", value_json='{"SKU-1": 1}'))
        session.commit()
    result = InventoryExternalMirrorService(factory).apply(
        sku="SKU-1", delta=-3, idempotency_key="invoice:2"
    )
    assert result.status == "shortage"
    assert result.new_stock == 0
