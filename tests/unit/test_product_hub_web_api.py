"""Tests for the Product Hub Read API (PR07)."""
from __future__ import annotations

from pathlib import Path
import uuid
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList, Product
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.desktop_client import ProductHubDesktopClient
from xw_office.web import ContentWebSettings, create_app


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    db_file = tmp_path / "product_hub_web.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    return f"sqlite:///{db_file}"


@pytest.fixture
def seeded_product(db_path: str) -> Product:
    engine = create_engine(db_path, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    repo = ProductHubRepository(factory)
    product, _variant = repo.create_product(
        sku="XW-1", name="Testprodukt", description="Eine Beschreibung"
    )
    repo.add_asset(
        product_id=product.id, role="COVER", storage_kind="EXTERNAL_URL", uri="https://x/c.jpg"
    )
    engine.dispose()
    return product


def _client(db_path: str, *, token: str = "secret-token", read_enabled: bool = True) -> TestClient:
    settings = ContentWebSettings(
        bootstrap_token=token, database_url=db_path, product_hub_catalog_read_enabled=read_enabled
    )
    return TestClient(create_app(settings))


def _auth_headers(token: str = "secret-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_products_endpoint_requires_bootstrap_token(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/products")
    assert response.status_code == 401


def test_products_endpoint_fails_closed_without_database_url() -> None:
    settings = ContentWebSettings(bootstrap_token="t")
    client = TestClient(create_app(settings))
    response = client.get("/api/v1/products", headers=_auth_headers("t"))
    assert response.status_code == 503


def test_products_endpoint_fails_closed_when_flag_disabled(
    db_path: str, seeded_product: Product
) -> None:
    client = _client(db_path, read_enabled=False)
    response = client.get("/api/v1/products", headers=_auth_headers())
    assert response.status_code == 503


def test_list_products_returns_seeded_product(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/products", headers=_auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["display_sku"] == "XW-1"
    assert "row_version" in payload["items"][0]


def test_list_products_includes_variant_summary(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/products", headers=_auth_headers())
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["variant_count"] == 1
    assert item["variants"][0]["sku"] == "XW-1"
    assert item["variants"][0]["is_default"] is True


def test_get_product_by_id(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get(f"/api/v1/products/{seeded_product.id}", headers=_auth_headers())
    assert response.status_code == 200
    assert response.json()["sku"] == "XW-1"


def test_get_product_unknown_id_returns_404(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get(f"/api/v1/products/{uuid.uuid4()}", headers=_auth_headers())
    assert response.status_code == 404


def test_get_product_by_sku(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/products/by-sku/XW-1", headers=_auth_headers())
    assert response.status_code == 200
    assert response.json()["id"] == str(seeded_product.id)


def test_get_product_by_sku_unknown_returns_404(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/products/by-sku/NOPE", headers=_auth_headers())
    assert response.status_code == 404


def test_get_product_variants(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get(f"/api/v1/products/{seeded_product.id}/variants", headers=_auth_headers())
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["is_default"] is True


def test_desktop_snapshot_exposes_versioned_variant_and_print_contract(
    db_path: str, seeded_product: Product
) -> None:
    engine = create_engine(db_path, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    repo = ProductHubRepository(factory)
    variant = repo.get_default_variant(seeded_product.id)
    assert variant is not None
    with factory() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.commit()
    price_list = repo.get_price_list_by_code("RETAIL_EUR")
    assert price_list is not None
    repo.set_price(variant.id, price_list_id=price_list.id, gross_amount=Decimal("27.90"))
    repo.upsert_print_rule(
        variant.id,
        min_stock_target=5,
        reprint_batch_qty=3,
        print_profile_id="noten_duplex",
        print_plan=[{"range": "Alle Seiten", "profile_id": "noten_duplex"}],
    )
    engine.dispose()

    client = _client(db_path)
    response = client.get(
        f"/api/v1/desktop/products/{seeded_product.id}/snapshot", headers=_auth_headers()
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "v1"
    assert payload["product"]["id"] == str(seeded_product.id)
    assert payload["variants"][0]["id"] == str(variant.id)
    assert payload["variants"][0]["print_rule"]["print_plan"] == [
        {"range": "Alle Seiten", "profile_id": "noten_duplex"}
    ]
    assert payload["variants"][0]["prices"][0]["gross_amount"] == "27.9000"

    def desktop_transport(request: httpx.Request) -> httpx.Response:
        upstream = client.get(request.url.path, headers=dict(request.headers))
        return httpx.Response(upstream.status_code, json=upstream.json())

    desktop_snapshot = ProductHubDesktopClient(
        base_url="https://hub.test",
        token="secret-token",
        transport=httpx.MockTransport(desktop_transport),
    ).get_product_snapshot(str(seeded_product.id))
    assert desktop_snapshot.product["id"] == payload["product"]["id"]
    assert desktop_snapshot.variants[0]["prices"][0]["gross_amount"] == "27.9000"


def test_get_product_assets(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get(f"/api/v1/products/{seeded_product.id}/assets", headers=_auth_headers())
    assert response.status_code == 200
    assert response.json()[0]["role"] == "COVER"


def test_get_product_improvements_empty(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get(
        f"/api/v1/products/{seeded_product.id}/improvements", headers=_auth_headers()
    )
    assert response.status_code == 200
    assert response.json() == []


def test_get_product_channels_empty(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get(f"/api/v1/products/{seeded_product.id}/channels", headers=_auth_headers())
    assert response.status_code == 200
    assert response.json() == []


def test_get_product_audit(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get(f"/api/v1/products/{seeded_product.id}/audit", headers=_auth_headers())
    assert response.status_code == 200


def test_get_product_readiness(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get(f"/api/v1/products/{seeded_product.id}/readiness", headers=_auth_headers())
    assert response.status_code == 200
    assert "wix_ready" in response.json()


def test_readiness_summary(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/catalog/readiness-summary", headers=_auth_headers())
    assert response.status_code == 200
    assert response.json()["total_products"] == 1


def test_list_products_pagination(db_path: str) -> None:
    engine = create_engine(db_path, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    repo = ProductHubRepository(factory)
    for i in range(5):
        repo.create_product(sku=f"XW-P{i}", name=f"Produkt {i}")
    engine.dispose()

    client = _client(db_path)
    response = client.get("/api/v1/products?limit=2&offset=0", headers=_auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 5
    assert len(payload["items"]) == 2


def test_list_products_search_filter(db_path: str) -> None:
    engine = create_engine(db_path, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    repo = ProductHubRepository(factory)
    repo.create_product(sku="XW-M1", name="MusikHeroes Sonderausgabe")
    repo.create_product(sku="XW-M2", name="Etwas anderes")
    engine.dispose()

    client = _client(db_path)
    response = client.get("/api/v1/products?search=MusikHeroes", headers=_auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["display_sku"] == "XW-M1"
