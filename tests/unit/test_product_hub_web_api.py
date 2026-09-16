"""Tests for the Product Hub Read API (PR07)."""
from __future__ import annotations

from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import Product
from xw_office.repositories.product_hub import ProductHubRepository
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
    assert payload["items"][0]["sku"] == "XW-1"
    assert "row_version" in payload["items"][0]


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
    assert payload["items"][0]["sku"] == "XW-M1"
