from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.inventory import LegacyInventoryShadowBridge
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


def test_external_shortage_is_persisted_in_legacy_shadow_conflict_queue() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    _product, variant = ProductHubRepository(factory).create_product(
        sku="SKU-1", name="Testnote", status="live", product_type="physical"
    )

    created = LegacyInventoryShadowBridge(factory).record_external_shortage(
        sku="SKU-1",
        requested_delta=-3,
        current_on_hand=1,
        target_on_hand=0,
        detail="Nur 1 von 3 Stücken vorhanden",
        external_reference="invoice-2:line-1",
    )

    assert created is True
    # The public inventory service presents the same durable queue to callers;
    # inspect it through the repository-backed service to avoid raw JSON checks.
    from xw_office.services.product_hub.inventory import InventoryV2Service

    items = InventoryV2Service(factory).list_legacy_shadow_conflicts()
    assert len(items) == 1
    assert items[0].variant_id == variant.id
    assert items[0].status == "shortage"
