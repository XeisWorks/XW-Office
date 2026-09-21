"""Tests for the Inventory V2 HTTP API (PR13/PR14)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.web import ContentWebSettings, create_app


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    db_file = tmp_path / "product_hub_inventory.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    return f"sqlite:///{db_file}"


def _client(
    db_path: str, *, token: str = "secret-token", edit_enabled: bool = True,
    shadow_enabled: bool = False,
) -> TestClient:
    settings = ContentWebSettings(
        bootstrap_token=token,
        database_url=db_path,
        product_hub_catalog_read_enabled=True,
        product_hub_edit_enabled=edit_enabled,
        inventory_shadow_enabled=shadow_enabled,
    )
    return TestClient(create_app(settings))


def _auth_headers(token: str = "secret-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_variant(db_path: str) -> str:
    engine = create_engine(db_path, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    repo = ProductHubRepository(factory)
    _product, variant = repo.create_product(sku="XW-7000", name="API Produkt")
    engine.dispose()
    return str(variant.id)


def test_inventory_routes_require_bootstrap_token(db_path: str) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/inventory/summary")
    assert response.status_code == 401


def test_summary_returns_zero_counts_when_empty(db_path: str) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/inventory/summary", headers=_auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["physical_products"] == 0
    assert body["low_stock"] == 0
    assert body["out_of_stock"] == 0


def test_cutover_readiness_is_read_only_and_explicitly_blocked_before_pr15(db_path: str) -> None:
    client = _client(db_path)
    response = client.get("/api/v1/inventory/cutover-readiness", headers=_auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["master_enabled"] is False
    assert body["eligible"] is False
    assert any(check["code"] == "legacy_mutation_paths" and check["state"] == "blocked" for check in body["checks"])


def test_legacy_baseline_preview_and_confirmed_apply(db_path: str) -> None:
    _seed_variant(db_path)
    engine = create_engine(db_path, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    from xw_office.repositories.settings_kv import SettingKvRepository

    SettingKvRepository(factory).set_value_json("inventory.stock_levels", '{"XW-7000": 9}')
    engine.dispose()
    client = _client(db_path, shadow_enabled=True)

    preview = client.get("/api/v1/inventory/legacy-baseline/preview", headers=_auth_headers())
    assert preview.status_code == 200
    assert preview.json()["items"][0]["status"] == "ready"
    applied = client.post(
        "/api/v1/inventory/legacy-baseline/apply",
        headers=_auth_headers(),
        json={"expected_source_hash": preview.json()["source_hash"]},
    )
    assert applied.status_code == 200
    assert applied.json()["applied_skus"] == ["XW-7000"]


def test_record_movement_requires_edit_enabled(db_path: str) -> None:
    variant_id = _seed_variant(db_path)
    client = _client(db_path, edit_enabled=False)
    response = client.post(
        "/api/v1/inventory/movements",
        headers=_auth_headers(),
        json={
            "variant_id": variant_id,
            "delta": 5,
            "reason": "import_baseline",
            "source": "test",
            "idempotency_key": "api-1",
        },
    )
    assert response.status_code == 503


def test_record_movement_and_read_stock(db_path: str) -> None:
    variant_id = _seed_variant(db_path)
    client = _client(db_path)

    created = client.post(
        "/api/v1/inventory/movements",
        headers=_auth_headers(),
        json={
            "variant_id": variant_id,
            "delta": 12,
            "reason": "import_baseline",
            "source": "test",
            "idempotency_key": "api-2",
        },
    )
    assert created.status_code == 201
    assert created.json()["movement"]["on_hand_after"] == 12
    assert created.json()["alert_opened"] is None

    stock = client.get(
        f"/api/v1/inventory/variants/{variant_id}/stock", headers=_auth_headers()
    ).json()
    assert stock[0]["on_hand"] == 12

    movements = client.get(
        f"/api/v1/inventory/variants/{variant_id}/movements", headers=_auth_headers()
    ).json()
    assert len(movements) == 1


def test_record_movement_negative_stock_returns_409(db_path: str) -> None:
    variant_id = _seed_variant(db_path)
    client = _client(db_path)
    response = client.post(
        "/api/v1/inventory/movements",
        headers=_auth_headers(),
        json={
            "variant_id": variant_id,
            "delta": -1,
            "reason": "sale",
            "source": "test",
            "idempotency_key": "api-3",
        },
    )
    assert response.status_code == 409


def test_set_thresholds_and_alert_crossing_via_movements(db_path: str) -> None:
    variant_id = _seed_variant(db_path)
    client = _client(db_path)

    client.put(
        f"/api/v1/inventory/variants/{variant_id}/thresholds",
        headers=_auth_headers(),
        json={"reorder_point": 5},
    )
    client.post(
        "/api/v1/inventory/movements",
        headers=_auth_headers(),
        json={
            "variant_id": variant_id, "delta": 10, "reason": "import_baseline",
            "source": "test", "idempotency_key": "api-4a",
        },
    )
    crossing = client.post(
        "/api/v1/inventory/movements",
        headers=_auth_headers(),
        json={
            "variant_id": variant_id, "delta": -6, "reason": "sale",
            "source": "test", "idempotency_key": "api-4b",
        },
    )
    assert crossing.json()["alert_opened"] is not None

    alerts = client.get("/api/v1/inventory/alerts", headers=_auth_headers()).json()
    assert len(alerts) == 1
    assert alerts[0]["type"] == "low_stock"

    resolved = client.post(
        f"/api/v1/inventory/alerts/{alerts[0]['id']}/resolve", headers=_auth_headers()
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_reconcile_endpoint(db_path: str) -> None:
    variant_id = _seed_variant(db_path)
    client = _client(db_path)
    client.post(
        "/api/v1/inventory/movements",
        headers=_auth_headers(),
        json={
            "variant_id": variant_id, "delta": 7, "reason": "import_baseline",
            "source": "test", "idempotency_key": "api-5",
        },
    )

    response = client.post(
        "/api/v1/inventory/reconcile",
        headers=_auth_headers(),
        json={"variant_id": variant_id, "sevdesk_on_hand": 4},
    )
    assert response.status_code == 200
    assert response.json()["drift_detected"] is True
