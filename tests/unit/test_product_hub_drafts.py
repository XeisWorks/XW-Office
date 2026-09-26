"""Contract tests for the durable, versioned product-wizard draft API."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.web import ContentWebSettings, create_app


def _client(tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'drafts.db'}"
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    return TestClient(create_app(ContentWebSettings(
        bootstrap_token="test-token", database_url=database_url,
        product_hub_catalog_read_enabled=True, product_hub_edit_enabled=True,
    )))


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_draft_autosave_options_and_selected_variant_are_resumable(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/v1/product-drafts", headers=_headers(), json={
        "template_code": "musicheroes", "data": {"title_full": "Cabernet Polka"},
    })
    assert created.status_code == 201
    draft = created.json()
    assert draft["current_step"] == 0
    assert draft["row_version"] == 1

    saved = client.patch(f"/api/v1/product-drafts/{draft['id']}", headers=_headers(), json={
        "expected_row_version": 1, "current_step": 2, "completed_steps": [0, 1],
        "data": {"title_full": "Cabernet Polka", "title_short": "Cabernet"},
    })
    assert saved.status_code == 200
    assert saved.json()["row_version"] == 2

    option = client.post(f"/api/v1/product-drafts/{draft['id']}/options", headers=_headers(), json={
        "expected_draft_row_version": 2, "name": "Besetzung",
        "values": ["Blechhauf'n", "Kleine Besetzung"],
    })
    assert option.status_code == 201

    variant = client.post(f"/api/v1/product-drafts/{draft['id']}/variants", headers=_headers(), json={
        "expected_draft_row_version": 3, "sku": "xw-draft-457",
        "option_values": {"Besetzung": "Blechhauf'n"}, "price_gross": "27.90", "tax_rate": "10",
    })
    assert variant.status_code == 201
    resumed = client.get(f"/api/v1/product-drafts/{draft['id']}", headers=_headers())
    assert resumed.status_code == 200
    assert resumed.json()["current_step"] == 2
    assert resumed.json()["options"][0]["name"] == "Besetzung"
    assert resumed.json()["variants"][0]["price_gross"] == "27.9000"


def test_stale_autosave_returns_current_draft_and_sku_check_is_not_reservation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = client.post("/api/v1/product-drafts", headers=_headers(), json={}).json()
    first = client.patch(f"/api/v1/product-drafts/{draft['id']}", headers=_headers(), json={
        "expected_row_version": 1, "current_step": 1,
    })
    assert first.status_code == 200
    stale = client.patch(f"/api/v1/product-drafts/{draft['id']}", headers=_headers(), json={
        "expected_row_version": 1, "current_step": 2,
    })
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_step"] == 1
    assert stale.json()["detail"]["row_version"] == 2

    assert client.get("/api/v1/product-drafts/sku-availability?sku=XW-FREE", headers=_headers()).json()["available"] is True
    engine = create_engine(f"sqlite:///{tmp_path / 'drafts.db'}", future=True)
    repo = ProductHubRepository(sessionmaker(bind=engine, expire_on_commit=False, future=True))
    repo.create_product(sku="XW-TAKEN", name="Taken")
    engine.dispose()
    assert client.get("/api/v1/product-drafts/sku-availability?sku=XW-TAKEN", headers=_headers()).json()["available"] is False


def test_templates_and_copy_create_an_isolated_editable_draft(tmp_path: Path) -> None:
    client = _client(tmp_path)
    templates = client.get("/api/v1/product-drafts/templates", headers=_headers())
    assert {item["code"] for item in templates.json()} == {
        "mnozil-single", "musicheroes-booklet", "additional-part"
    }
    engine = create_engine(f"sqlite:///{tmp_path / 'drafts.db'}", future=True)
    repo = ProductHubRepository(sessionmaker(bind=engine, expire_on_commit=False, future=True))
    product, variant = repo.create_product(sku="XW-COPY-1", name="Original")
    copied = client.post(f"/api/v1/products/{product.id}/copy-draft", headers=_headers(), json={})
    assert copied.status_code == 201
    assert copied.json()["source_product_id"] == str(product.id)
    assert copied.json()["variants"][0]["sku"] == "XW-COPY-1-COPY"
    assert copied.json()["data"]["cover_status"] == "regenerate_required"
    assert repo.get_variant(variant.id).sku == "XW-COPY-1"
    engine.dispose()
