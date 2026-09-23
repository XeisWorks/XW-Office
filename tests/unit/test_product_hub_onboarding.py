from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.onboarding import ProductOnboardingService
from xw_office.services.sevdesk.part_client import SevdeskPart
from xw_office.services.wix.product_details_client import CatalogVersion


class FakeParts:
    def __init__(self) -> None:
        self.parts: dict[str, SevdeskPart] = {}
        self.fail_create = False

    def list_part_categories(self) -> list[dict[str, str]]:
        return [{"id": "7", "name": "Noten"}]

    def find_part_by_sku(self, sku: str, *, strict: bool = False) -> SevdeskPart | None:
        return self.parts.get(sku)

    def create_part(self, payload: dict[str, object]) -> SevdeskPart:
        if self.fail_create:
            raise RuntimeError("sevDesk test failure")
        sku = str(payload["partNumber"])
        part = SevdeskPart(id=f"sev-{len(self.parts) + 1}", sku=sku, name=str(payload["name"]))
        self.parts[sku] = part
        return part


class FakeWixCatalog:
    def __init__(self) -> None:
        self.products: list[SimpleNamespace] = []

    def list_products(self, *, include_hidden: bool = False, strict: bool = False):
        assert include_hidden is True
        return list(self.products)


class FakeWixDetails:
    def __init__(self, catalog: FakeWixCatalog) -> None:
        self.catalog = catalog
        self.fail_create = False

    def has_credentials(self) -> bool:
        return True

    def create_product(self, *, name: str, sku: str, product_type: str, price: str):
        if self.fail_create:
            raise RuntimeError("Wix test failure")
        product_id = f"wix-{len(self.catalog.products) + 1}"
        self.catalog.products.append(SimpleNamespace(id=product_id, all_skus=(sku,)))
        return product_id, CatalogVersion.V3


def _service(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'onboarding.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.commit()
    parts = FakeParts()
    wix_catalog = FakeWixCatalog()
    wix_details = FakeWixDetails(wix_catalog)
    service = ProductOnboardingService(
        factory,
        sevdesk_parts=parts,  # type: ignore[arg-type]
        wix_catalog=wix_catalog,  # type: ignore[arg-type]
        wix_details=wix_details,  # type: ignore[arg-type]
        sevdesk_configured=True,
    )
    return service, factory, parts, wix_catalog, wix_details


def _onboard(service: ProductOnboardingService, **overrides):
    values = {
        "sku": "xw-new-1",
        "name": "Neues Produkt",
        "product_type": "physical",
        "price_gross": Decimal("19.90"),
        "tax_rate": Decimal(10),
        "sevdesk_category_id": "7",
        "sevdesk_category_name": "Noten",
    }
    values.update(overrides)
    return service.onboard(**values)


def test_onboarding_creates_hub_price_and_both_channel_mappings(tmp_path: Path) -> None:
    service, factory, parts, wix_catalog, _details = _service(tmp_path)

    result = _onboard(service)

    assert result.complete is True
    assert [item.state for item in result.channels] == ["created", "created"]
    assert "XW-NEW-1" in parts.parts
    assert wix_catalog.products[0].all_skus == ("XW-NEW-1",)
    repo = ProductHubRepository(factory)
    product = repo.get_product(result.product_id)
    variant = repo.get_default_variant(result.product_id)
    assert product is not None and product.status == "draft"
    assert variant is not None
    prices = repo.list_prices(variant.id)
    assert prices[0].gross_amount == Decimal("19.9000")
    product_channels = repo.list_channel_mappings(
        entity_type="product", internal_entity_id=product.id
    )
    variant_channels = repo.list_channel_mappings(
        entity_type="variant", internal_entity_id=variant.id
    )
    assert {item.channel for item in product_channels} == {"wix"}
    assert {item.channel for item in variant_channels} == {"sevdesk"}


def test_partial_failure_can_resume_without_duplicate_hub_or_sevdesk(tmp_path: Path) -> None:
    service, factory, parts, wix_catalog, wix_details = _service(tmp_path)
    wix_details.fail_create = True

    first = _onboard(service)
    assert first.complete is False
    assert first.channels[0].state == "created"
    assert first.channels[1].state == "error"

    wix_details.fail_create = False
    resumed = _onboard(service, resume_product_id=first.product_id)

    assert resumed.complete is True
    assert resumed.product_id == first.product_id
    assert resumed.channels[0].state == "synced"
    assert len(parts.parts) == 1
    assert len(wix_catalog.products) == 1
    assert len(ProductHubRepository(factory).list_products()) == 1


def test_existing_sku_requires_explicit_resume_product_id(tmp_path: Path) -> None:
    service, _factory, _parts, _wix_catalog, _wix_details = _service(tmp_path)
    _onboard(service)

    try:
        _onboard(service)
    except ValueError as exc:
        assert "existiert bereits" in str(exc)
    else:
        raise AssertionError("duplicate onboarding must fail")
