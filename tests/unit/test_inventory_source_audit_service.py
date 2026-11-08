from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import Product, ProductVariant
from xw_office.services.product_hub.inventory import InventoryV2Service


def test_inventory_source_audit_is_read_only_and_reports_missing_sources() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        product = Product(id=uuid.uuid4(), sku="AUDIT-1", name="Audit", slug="audit-1", status="live", product_type="physical", active=True, attributes={})
        session.add(product)
        session.flush()
        session.add(ProductVariant(id=uuid.uuid4(), product_id=product.id, sku="AUDIT-1", name="Audit", active=True, stock_enabled=True, attributes={}, option_values={}))
        session.commit()
    report = InventoryV2Service(factory).audit_inventory_sources()
    assert report.active_physical_count == 1
    assert report.missing_sellable_since_count == 1
    assert report.warning_count >= 1
    with factory() as session:
        assert session.query(ProductVariant).count() == 1
