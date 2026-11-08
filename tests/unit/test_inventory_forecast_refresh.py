from __future__ import annotations

import datetime
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import Product, ProductVariant
from xw_office.models.product_hub_inventory import InventoryStock
from xw_office.services.product_hub.inventory_forecast_refresh import InventoryForecastRefreshService


class _Provider:
    def list_invoices_for_year(self, year: int):
        return [{"id": "invoice-1", "status": 200, "invoiceDate": "2026-01-15"}] if year == 2026 else []

    def list_invoice_positions(self, invoice_id: str):
        return [{"quantity": 10, "part": {"number": "FORECAST-1"}}]

    def list_credit_notes_for_year(self, year: int):
        return []

    def list_credit_note_positions(self, credit_note_id: str):
        return []


def test_refresh_service_persists_auto_reorder_point() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        product = Product(id=uuid.uuid4(), sku="FORECAST-1", name="Forecast", slug="forecast-1", status="live", product_type="physical", active=True, release_date=datetime.date(2025, 1, 1), attributes={})
        session.add(product)
        session.flush()
        session.add(ProductVariant(id=uuid.uuid4(), product_id=product.id, sku="FORECAST-1", name="Forecast", active=True, stock_enabled=True, attributes={}, option_values={}))
        session.commit()
    result = InventoryForecastRefreshService(factory, _Provider()).refresh(as_of=datetime.date(2026, 8, 1))
    assert result.refreshed == 1
    assert result.results[0].automatic_reorder_point == 2
