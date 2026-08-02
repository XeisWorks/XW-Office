"""Security and health contract for the Phase-1 Content web service."""
from fastapi.testclient import TestClient

from xw_office.web import ContentWebSettings, create_app


def test_health_and_landing_are_public_and_data_free() -> None:
    client = TestClient(create_app(ContentWebSettings()))

    health = client.get("/health")
    landing = client.get("/")

    assert health.status_code == 200
    assert health.json()["service"] == "xw-content-web"
    assert landing.status_code == 200
    assert "XeisWorks" in landing.text
    assert "noch nicht konfiguriert" in landing.text


def test_content_api_fails_closed_without_configured_token() -> None:
    client = TestClient(create_app(ContentWebSettings()))

    response = client.get("/api/v1/content/brands")

    assert response.status_code == 503


def test_content_api_rejects_wrong_token() -> None:
    client = TestClient(create_app(ContentWebSettings(bootstrap_token="correct-token")))

    response = client.get(
        "/api/v1/content/brands",
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_content_api_returns_validated_brand_profiles() -> None:
    client = TestClient(create_app(ContentWebSettings(bootstrap_token="correct-token")))

    response = client.get(
        "/api/v1/content/brands",
        headers={"Authorization": "Bearer correct-token"},
    )

    assert response.status_code == 200
    assert [brand["id"] for brand in response.json()] == ["xeisworks", "musikheroes"]
