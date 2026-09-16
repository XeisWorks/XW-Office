"""Tests for the dealer sharing HTTP API (PR12): admin CRUD + public share routes."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.web import ContentWebSettings, create_app


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    db_file = tmp_path / "product_hub_sharing.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.add(PriceList(id=uuid.uuid4(), code="B2B_EUR", name="B2B EUR"))
        session.commit()
    engine.dispose()
    return f"sqlite:///{db_file}"


def _client(db_path: str, *, token: str = "secret-token", edit_enabled: bool = True) -> TestClient:
    settings = ContentWebSettings(
        bootstrap_token=token,
        database_url=db_path,
        product_hub_catalog_read_enabled=True,
        product_hub_edit_enabled=edit_enabled,
    )
    return TestClient(create_app(settings))


def _auth_headers(token: str = "secret-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_b2b_live_product(db_path: str) -> None:
    engine = create_engine(db_path, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    repo = ProductHubRepository(factory)
    product, variant = repo.create_product(sku="XW-4000", name="Share Produkt", status="live")
    tag = repo.get_or_create_tag(code="B2B", label="B2B")
    repo.add_product_tag(product_id=product.id, tag_id=tag.id)
    retail = repo.get_price_list_by_code("RETAIL_EUR")
    assert retail is not None
    repo.set_price(variant.id, price_list_id=retail.id, gross_amount=Decimal("29.99"))
    engine.dispose()


# -- admin API -------------------------------------------------------------------------


def test_admin_shares_fail_closed_when_edit_disabled(db_path: str) -> None:
    client = _client(db_path, edit_enabled=False)
    response = client.get("/api/v1/shares", headers=_auth_headers())
    assert response.status_code == 503


def test_admin_shares_require_bootstrap_token(db_path: str) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/shares")
    assert response.status_code == 401


def test_create_list_revoke_share(db_path: str) -> None:
    client = _client(db_path)

    created = client.post(
        "/api/v1/shares", headers=_auth_headers(), json={"title": "Herbstkatalog"}
    )
    assert created.status_code == 201
    body = created.json()
    assert "token" in body and len(body["token"]) > 20
    assert body["share_url"].endswith(f"/share/{body['token']}")
    share_id = body["id"]

    listed = client.get("/api/v1/shares", headers=_auth_headers()).json()
    assert len(listed) == 1
    assert "token" not in listed[0]  # never leaked on listing

    revoked = client.post(f"/api/v1/shares/{share_id}/revoke", headers=_auth_headers())
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


def test_create_share_rejects_unknown_field(db_path: str) -> None:
    client = _client(db_path)
    response = client.post(
        "/api/v1/shares",
        headers=_auth_headers(),
        json={"title": "x", "field_whitelist": ["sku", "purchase_cost"]},
    )
    assert response.status_code == 400


def test_revoke_unknown_share_returns_404(db_path: str) -> None:
    client = _client(db_path)
    response = client.post(f"/api/v1/shares/{uuid.uuid4()}/revoke", headers=_auth_headers())
    assert response.status_code == 404


# -- public routes (no bootstrap token) ------------------------------------------------


def _create_share(client: TestClient, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"title": "Öffentlicher Katalog"}
    payload.update(overrides)
    response = client.post("/api/v1/shares", headers=_auth_headers(), json=payload)
    assert response.status_code == 201
    return response.json()


def test_public_share_view_works_without_bootstrap_token(db_path: str) -> None:
    _seed_b2b_live_product(db_path)
    client = _client(db_path)
    share = _create_share(client)

    response = client.get(f"/share/{share['token']}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "XW-4000" in response.text
    assert "Share Produkt" in response.text


def test_public_share_unknown_token_returns_404(db_path: str) -> None:
    client = _client(db_path)
    response = client.get("/share/not-a-real-token")
    assert response.status_code == 404


def test_public_share_revoked_returns_410(db_path: str) -> None:
    client = _client(db_path)
    share = _create_share(client)
    client.post(f"/api/v1/shares/{share['id']}/revoke", headers=_auth_headers())

    response = client.get(f"/share/{share['token']}")
    assert response.status_code == 410


def test_public_share_csv_export(db_path: str) -> None:
    _seed_b2b_live_product(db_path)
    client = _client(db_path)
    share = _create_share(client)

    response = client.get(f"/share/{share['token']}/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "XW-4000" in response.text


def test_public_share_csv_export_forbidden_when_disallowed(db_path: str) -> None:
    client = _client(db_path)
    share = _create_share(client, allow_csv=False)

    response = client.get(f"/share/{share['token']}/export.csv")
    assert response.status_code == 403


def test_public_share_xlsx_export(db_path: str) -> None:
    _seed_b2b_live_product(db_path)
    client = _client(db_path)
    share = _create_share(client)

    response = client.get(f"/share/{share['token']}/export.xlsx")

    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(response.content) > 0


def test_public_share_routes_fail_closed_when_read_disabled(db_path: str) -> None:
    settings = ContentWebSettings(
        bootstrap_token="t",
        database_url=db_path,
        product_hub_catalog_read_enabled=False,
    )
    client = TestClient(create_app(settings))
    response = client.get("/share/anything")
    assert response.status_code == 503
