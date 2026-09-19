"""Tests for the Product Hub Edit API (PR09)."""

from __future__ import annotations

from pathlib import Path
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList, Product, Tag
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.web import ContentWebSettings, create_app


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    db_file = tmp_path / "product_hub_edit.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.add(Tag(id=uuid.uuid4(), code="AMAZON", label="Amazon"))
        session.commit()
    engine.dispose()
    return f"sqlite:///{db_file}"


@pytest.fixture
def seeded_product(db_path: str) -> Product:
    engine = create_engine(db_path, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    repo = ProductHubRepository(factory)
    product, _variant = repo.create_product(sku="XW-EDIT-1", name="Editable Book")
    engine.dispose()
    return product


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


def test_edit_endpoints_fail_closed_when_disabled(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path, edit_enabled=False)
    response = client.patch(
        f"/api/v1/products/{seeded_product.id}",
        headers=_auth_headers(),
        json={"expected_row_version": 1, "name": "X"},
    )
    assert response.status_code == 503


def test_patch_product_updates_and_bumps_row_version(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.patch(
        f"/api/v1/products/{seeded_product.id}",
        headers=_auth_headers(),
        json={"expected_row_version": 1, "name": "Renamed Book"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Book"
    assert body["row_version"] == 2


def test_rename_product_sku_updates_matching_variant_and_keeps_old_alias(
    db_path: str, seeded_product: Product
) -> None:
    client = _client(db_path)
    response = client.post(
        f"/api/v1/products/{seeded_product.id}/rename-sku",
        headers=_auth_headers(),
        json={"expected_row_version": 1, "sku": " xw-edit-1-d "},
    )

    assert response.status_code == 200
    assert response.json()["sku"] == "XW-EDIT-1-D"
    variants = client.get(
        f"/api/v1/products/{seeded_product.id}/variants", headers=_auth_headers()
    ).json()
    assert variants[0]["sku"] == "XW-EDIT-1-D"
    old_sku = client.get("/api/v1/products/by-sku/XW-EDIT-1", headers=_auth_headers())
    assert old_sku.status_code == 200
    assert old_sku.json()["sku"] == "XW-EDIT-1-D"


def test_patch_product_stale_row_version_returns_409_with_current_state(
    db_path: str, seeded_product: Product
) -> None:
    client = _client(db_path)
    response = client.patch(
        f"/api/v1/products/{seeded_product.id}",
        headers=_auth_headers(),
        json={"expected_row_version": 999, "name": "X"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["name"] == "Editable Book"
    assert detail["row_version"] == 1


def test_patch_product_variant(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    variants = client.get(
        f"/api/v1/products/{seeded_product.id}/variants", headers=_auth_headers()
    ).json()
    variant_id = variants[0]["id"]
    response = client.patch(
        f"/api/v1/products/{seeded_product.id}/variants/{variant_id}",
        headers=_auth_headers(),
        json={"expected_row_version": 1, "active": False},
    )
    assert response.status_code == 200
    assert response.json()["active"] is False
    assert response.json()["row_version"] == 2


def test_add_and_remove_tag(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    add_response = client.post(
        f"/api/v1/products/{seeded_product.id}/tags",
        headers=_auth_headers(),
        json={"tag_code": "AMAZON"},
    )
    assert add_response.status_code == 201
    tag_id = add_response.json()["id"]

    list_response = client.get(
        f"/api/v1/products/{seeded_product.id}/tags", headers=_auth_headers()
    )
    assert [t["code"] for t in list_response.json()] == ["AMAZON"]

    delete_response = client.delete(
        f"/api/v1/products/{seeded_product.id}/tags/{tag_id}", headers=_auth_headers()
    )
    assert delete_response.status_code == 204
    assert (
        client.get(f"/api/v1/products/{seeded_product.id}/tags", headers=_auth_headers()).json()
        == []
    )


def test_add_unknown_tag_returns_404(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.post(
        f"/api/v1/products/{seeded_product.id}/tags",
        headers=_auth_headers(),
        json={"tag_code": "DOES-NOT-EXIST"},
    )
    assert response.status_code == 404


def test_add_and_remove_identifier(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    add_response = client.post(
        f"/api/v1/products/{seeded_product.id}/identifiers",
        headers=_auth_headers(),
        json={"scheme": "ASIN", "value": "B000TEST"},
    )
    assert add_response.status_code == 201
    identifier_id = add_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/products/{seeded_product.id}/identifiers/{identifier_id}",
        headers=_auth_headers(),
    )
    assert delete_response.status_code == 204


def test_set_variant_price(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    variant_id = client.get(
        f"/api/v1/products/{seeded_product.id}/variants", headers=_auth_headers()
    ).json()[0]["id"]

    response = client.post(
        f"/api/v1/products/{seeded_product.id}/variants/{variant_id}/prices",
        headers=_auth_headers(),
        json={"price_list_code": "RETAIL_EUR", "gross_amount": "19.99"},
    )
    assert response.status_code == 201
    assert response.json()["gross_amount"] == "19.99"


def test_set_variant_price_unknown_price_list_returns_404(
    db_path: str, seeded_product: Product
) -> None:
    client = _client(db_path)
    variant_id = client.get(
        f"/api/v1/products/{seeded_product.id}/variants", headers=_auth_headers()
    ).json()[0]["id"]

    response = client.post(
        f"/api/v1/products/{seeded_product.id}/variants/{variant_id}/prices",
        headers=_auth_headers(),
        json={"price_list_code": "DOES-NOT-EXIST", "gross_amount": "19.99"},
    )
    assert response.status_code == 404


def test_upsert_print_rule_create_then_update(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    variant_id = client.get(
        f"/api/v1/products/{seeded_product.id}/variants", headers=_auth_headers()
    ).json()[0]["id"]

    created = client.put(
        f"/api/v1/products/{seeded_product.id}/variants/{variant_id}/print-rule",
        headers=_auth_headers(),
        json={"min_stock_target": 10},
    )
    assert created.status_code == 200
    assert created.json()["min_stock_target"] == 10
    assert created.json()["row_version"] == 1

    updated = client.put(
        f"/api/v1/products/{seeded_product.id}/variants/{variant_id}/print-rule",
        headers=_auth_headers(),
        json={"expected_row_version": 1, "min_stock_target": 20},
    )
    assert updated.status_code == 200
    assert updated.json()["min_stock_target"] == 20
    assert updated.json()["row_version"] == 2


def test_create_and_resolve_improvement(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    created = client.post(
        f"/api/v1/products/{seeded_product.id}/improvements",
        headers=_auth_headers(),
        json={"description": "Typo on page 3"},
    )
    assert created.status_code == 201
    improvement_id = created.json()["id"]
    assert created.json()["status"] == "open"

    resolved = client.patch(
        f"/api/v1/products/{seeded_product.id}/improvements/{improvement_id}",
        headers=_auth_headers(),
        json={"expected_row_version": 1, "status": "resolved"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"] is not None


def test_create_edition_resolves_improvements(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    improvement_id = client.post(
        f"/api/v1/products/{seeded_product.id}/improvements",
        headers=_auth_headers(),
        json={"description": "Typo"},
    ).json()["id"]

    response = client.post(
        f"/api/v1/products/{seeded_product.id}/editions",
        headers=_auth_headers(),
        json={"label": "2nd Edition", "resolve_improvement_ids": [improvement_id]},
    )
    assert response.status_code == 201
    assert response.json()["label"] == "2nd Edition"

    improvements = client.get(
        f"/api/v1/products/{seeded_product.id}/improvements", headers=_auth_headers()
    ).json()
    assert improvements[0]["status"] == "resolved"


def test_edit_creates_audit_log_entry(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    client.patch(
        f"/api/v1/products/{seeded_product.id}",
        headers=_auth_headers(),
        json={"expected_row_version": 1, "name": "Renamed Book"},
    )
    audit = client.get(
        f"/api/v1/products/{seeded_product.id}/audit", headers=_auth_headers()
    ).json()
    assert any(entry["action"] == "update" for entry in audit)


# -- Content generation (OpenAI-backed description/bullet-point drafting) -----------


def _openai_transport(*, output_text: str, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"output_text": output_text})

    return httpx.MockTransport(handler)


def test_generate_content_returns_draft_without_saving(
    db_path: str, seeded_product: Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    transport = _openai_transport(
        output_text='{"description": "Ein tolles Stueck.", "bullet_points": ["Besetzung: Blasorchester"]}'
    )
    original = httpx.Client

    class _MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.Client = _MockClient  # type: ignore[assignment]
    try:
        client = _client(db_path)
        response = client.post(
            f"/api/v1/products/{seeded_product.id}/generate-content", headers=_auth_headers()
        )
    finally:
        httpx.Client = original  # type: ignore[assignment]

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Ein tolles Stueck."
    assert body["bullet_points"] == ["Besetzung: Blasorchester"]

    detail = client.get(f"/api/v1/products/{seeded_product.id}", headers=_auth_headers()).json()
    assert detail["description"] != "Ein tolles Stueck."
    assert "bullet_points" not in detail.get("attributes", {})


def test_generate_content_without_api_key_returns_503(
    db_path: str, seeded_product: Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = _client(db_path)
    response = client.post(
        f"/api/v1/products/{seeded_product.id}/generate-content", headers=_auth_headers()
    )
    assert response.status_code == 503


def test_generate_content_requires_edit_enabled(
    db_path: str, seeded_product: Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = _client(db_path, edit_enabled=False)
    response = client.post(
        f"/api/v1/products/{seeded_product.id}/generate-content", headers=_auth_headers()
    )
    assert response.status_code == 503


def test_put_bullet_points_saves_into_attributes(db_path: str, seeded_product: Product) -> None:
    client = _client(db_path)
    response = client.put(
        f"/api/v1/products/{seeded_product.id}/bullet-points",
        headers=_auth_headers(),
        json={"expected_row_version": 1, "bullet_points": ["Punkt A", "Punkt B"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["attributes"]["bullet_points"] == ["Punkt A", "Punkt B"]
    assert body["row_version"] == 2


def test_put_bullet_points_stale_row_version_returns_409(
    db_path: str, seeded_product: Product
) -> None:
    client = _client(db_path)
    response = client.put(
        f"/api/v1/products/{seeded_product.id}/bullet-points",
        headers=_auth_headers(),
        json={"expected_row_version": 999, "bullet_points": ["Punkt A"]},
    )
    assert response.status_code == 409
