from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import Product, ProductVariant
from xw_office.models.product_hub_inventory import InventoryAlert, InventoryLocation, InventoryStock
from xw_office.services.product_hub.inventory_alert_tasks import InventoryAlertTaskService
from xw_office.models.inventory_alert_task import InventoryAlertTask
import pytest


class _Mail:
    def __init__(self) -> None:
        self.sent = []

    @staticmethod
    def plain_text_to_html(value: str) -> str:
        return value

    def send_mail(self, **kwargs: Any) -> None:
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
    assert "Alarmmodus: auto" in mail.sent[0]["text_body"]
    assert "Zielbestand: 5" in mail.sent[0]["text_body"]
    assert "Empfohlene Bestell-/Nachdruckmenge: 3" in mail.sent[0]["text_body"]
    assert "Durchschnittlicher Monatsverkauf:" in mail.sent[0]["text_body"]
    assert "Produktlink: /app/products/" in mail.sent[0]["text_body"]
    tasks = service.list_tasks(status="sent")
    assert len(tasks) == 1
    assert tasks[0].alert_id == alert_id


def test_task_mail_uses_explicit_target_stock_for_order_quantity() -> None:
    factory, alert_id = _factory()
    with factory() as session:
        stock = session.query(InventoryStock).one()
        stock.target_stock = 10
        session.commit()
    mail = _Mail()
    InventoryAlertTaskService(factory).create_and_send(alert_id, mail_delivery=mail)
    assert "Zielbestand: 10" in mail.sent[0]["text_body"]
    assert "Empfohlene Bestell-/Nachdruckmenge: 8" in mail.sent[0]["text_body"]


def test_reentrant_caller_cannot_send_an_already_claimed_task() -> None:
    factory, alert_id = _factory()
    service = InventoryAlertTaskService(factory)

    class ReentrantMail(_Mail):
        def send_mail(self, **kwargs: Any) -> None:
            result = service.create_and_send(alert_id, mail_delivery=self, explicit_resend=True)
            assert result.status == "pending"
            super().send_mail(**kwargs)

    mail = ReentrantMail()
    assert service.create_and_send(alert_id, mail_delivery=mail).status == "sent"
    assert len(mail.sent) == 1


def test_transport_timeout_is_unknown_and_is_not_blindly_retried() -> None:
    factory, alert_id = _factory()
    service = InventoryAlertTaskService(factory)

    class TimeoutMail(_Mail):
        def send_mail(self, **kwargs: Any) -> None:
            super().send_mail(**kwargs)
            raise TimeoutError("Graph response lost")

    mail = TimeoutMail()
    assert service.create_and_send(alert_id, mail_delivery=mail).status == "unknown"
    assert service.create_and_send(alert_id, mail_delivery=mail).status == "unknown"
    assert len(mail.sent) == 1


@pytest.mark.parametrize("status", ["sent", "unknown", "failed"])
def test_only_explicit_resend_can_reuse_a_completed_attempt(status: str) -> None:
    factory, alert_id = _factory()
    service = InventoryAlertTaskService(factory)
    mail = _Mail()
    service.create_and_send(alert_id, mail_delivery=mail)
    with factory() as session:
        task = session.query(InventoryAlertTask).one()
        task.status = status
        session.commit()
    assert service.create_and_send(alert_id, mail_delivery=mail).status == status
    assert len(mail.sent) == 1
    assert service.create_and_send(alert_id, mail_delivery=mail, explicit_resend=True).status == "sent"
    assert len(mail.sent) == 2
