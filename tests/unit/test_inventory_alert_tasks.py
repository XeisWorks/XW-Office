from __future__ import annotations

import datetime
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import Product, ProductVariant
from xw_office.models.product_hub_inventory import InventoryAlert, InventoryLocation, InventoryStock
from xw_office.services.product_hub.inventory_alert_tasks import InventoryAlertTaskService


class _Mail:
    def __init__(self) -> None:
        self.sent = []

    @staticmethod
    def plain_text_to_html(value: str) -> str:
        return value

    def send_mail(self, **kwargs) -> None:
        self.sent.append(kwargs)


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        product = Product(id=uuid.uuid4(), sku="ALARM-1", name="Alarmtitel", slug="alarmtitel", status="live", product_type="physical", active=True, attributes={})
        session.add(product)
        session.flush()
        variant = ProductVariant(id=uuid.uuid4(), product_id=product.id, sku="ALARM-1", name="Alarmtitel", active=True, stock_enabled=True, attributes={}, option_values={})
        location = InventoryLocation(id=uuid.uuid4(), code="MAIN", name="Hauptlager")
        session.add_all([variant, location])
        session.flush()
        session.add(InventoryStock(variant_id=variant.id, location_id=location.id, on_hand=2, reorder_point=5))
        now = datetime.datetime.now(datetime.timezone.utc)
        alert = InventoryAlert(id=uuid.uuid4(), variant_id=variant.id, location_id=location.id, type="low_stock", status="open", threshold=5, observed_stock=2, first_triggered_at=now, last_triggered_at=now)
        session.add(alert)
        session.commit()
        return factory, alert.id


def test_task_mail_contains_inventory_facts_and_is_deduplicated() -> None:
    factory, alert_id = _factory()
    service = InventoryAlertTaskService(factory)
    mail = _Mail()
    first = service.create_and_send(alert_id, mail_delivery=mail, sales_average_monthly=4.5, three_month_demand=14)
    second = service.create_and_send(alert_id, mail_delivery=mail, sales_average_monthly=4.5, three_month_demand=14)
    assert first.status == "sent"
    assert second.status == "sent"
    assert len(mail.sent) == 1
    assert "ALARM-1" in mail.sent[0]["text_body"]
    assert "Ist-Bestand: 2" in mail.sent[0]["text_body"]
    assert "Durchschnittlicher Monatsverkauf:" in mail.sent[0]["text_body"]
    assert "Produktlink: /app/products/" in mail.sent[0]["text_body"]
