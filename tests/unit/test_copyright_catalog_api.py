"""The copyright export is a scoped metadata feed, not Product Hub access."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.web import ContentWebSettings, create_app


def test_catalog_requires_own_token_and_exposes_only_scoped_metadata(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'copyright_catalog.db'}"
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    repo = ProductHubRepository(sessionmaker(bind=engine, expire_on_commit=False, future=True))
    selected, _ = repo.create_product(
        sku="SCORE-1", name="Synthetic score", brand_name="Mnozil Brass"
    )
    repo.create_product(sku="OTHER-1", name="Other score", brand_name="Other Publisher")
    repo.create_product(sku="UNKNOWN-1", name="Unassigned score", category="Notenausgabe")
    repo.create_edition(product_id=selected.id, label="First edition")
    client = TestClient(
        create_app(
            ContentWebSettings(
                bootstrap_token="broad-token",
                copyright_catalog_read_token="narrow-token",
                database_url=database_url,
            )
        )
    )
    path = "/api/v1/copyright/catalog"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer broad-token"}).status_code == 401
    response = client.get(path, headers={"Authorization": "Bearer narrow-token"})
    assert response.status_code == 200
    rows = response.json()["products"]
    assert len(rows) == 2
    selected_row = next(row for row in rows if row["product_id"] == str(selected.id))
    assert selected_row["brand"] == "Mnozil Brass"
    assert selected_row["variants"][0]["sku"] == "SCORE-1"
    assert selected_row["editions"][0]["label"] == "First edition"
    assert any(row["brand"] == "" for row in rows)
    assert "price" not in str(response.json()).lower()
    assert "attributes" not in str(response.json()).lower()
    assert client.post(path, headers={"Authorization": "Bearer narrow-token"}).status_code == 405
    engine.dispose()


def test_catalog_fails_closed_without_scoped_token() -> None:
    client = TestClient(create_app(ContentWebSettings()))
    assert client.get("/api/v1/copyright/catalog").status_code == 503
