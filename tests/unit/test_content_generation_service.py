"""Tests for the OpenAI description/bullet-point drafting service (Product Hub).

Network is mocked via a swapped-in ``httpx.Client`` subclass — same pattern as
``test_wix_product_details_client.py`` — no real API calls.
"""
from __future__ import annotations

import httpx
import pytest

from xw_office.services.product_hub.content_generation import (
    ContentGenerationError,
    ContentGenerationService,
    ProductContentContext,
)


def _responses_transport(*, output_text: str, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"output_text": output_text})

    return httpx.MockTransport(handler)


def _patched(transport: httpx.MockTransport):
    original = httpx.Client

    class _MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.Client = _MockClient  # type: ignore[assignment]
    return original


def _restore(original) -> None:
    httpx.Client = original  # type: ignore[assignment]


def test_generate_returns_description_and_bullet_points() -> None:
    transport = _responses_transport(
        output_text='{"description": "Ein schoenes Stueck.", "bullet_points": ["Besetzung: Blasorchester", "Schwierigkeit: mittel"]}'
    )
    original = _patched(transport)
    try:
        service = ContentGenerationService(api_key="sk-test")
        result = service.generate(ProductContentContext(name="Alpenfest Marsch"))
    finally:
        _restore(original)

    assert result.description == "Ein schoenes Stueck."
    assert result.bullet_points == ["Besetzung: Blasorchester", "Schwierigkeit: mittel"]


def test_generate_caps_bullet_points_at_five() -> None:
    bullets = [f"Punkt {i}" for i in range(8)]
    transport = _responses_transport(
        output_text='{"description": "Text.", "bullet_points": ' + str(bullets).replace("'", '"') + "}"
    )
    original = _patched(transport)
    try:
        service = ContentGenerationService(api_key="sk-test")
        result = service.generate(ProductContentContext(name="Test"))
    finally:
        _restore(original)

    assert len(result.bullet_points) == 5


def test_generate_raises_without_api_key() -> None:
    service = ContentGenerationService(api_key="")
    with pytest.raises(ContentGenerationError, match="nicht konfiguriert"):
        service.generate(ProductContentContext(name="Test"))


def test_generate_raises_on_http_error() -> None:
    transport = _responses_transport(output_text="", status_code=500)
    original = _patched(transport)
    try:
        service = ContentGenerationService(api_key="sk-test")
        with pytest.raises(ContentGenerationError, match="fehlgeschlagen"):
            service.generate(ProductContentContext(name="Test"))
    finally:
        _restore(original)


def test_generate_raises_on_invalid_json() -> None:
    transport = _responses_transport(output_text="not json at all")
    original = _patched(transport)
    try:
        service = ContentGenerationService(api_key="sk-test")
        with pytest.raises(ContentGenerationError, match="JSON"):
            service.generate(ProductContentContext(name="Test"))
    finally:
        _restore(original)


def test_generate_raises_on_empty_description() -> None:
    transport = _responses_transport(output_text='{"description": "", "bullet_points": []}')
    original = _patched(transport)
    try:
        service = ContentGenerationService(api_key="sk-test")
        with pytest.raises(ContentGenerationError, match="keine Beschreibung"):
            service.generate(ProductContentContext(name="Test"))
    finally:
        _restore(original)


def test_generate_strips_markdown_code_fence() -> None:
    transport = _responses_transport(
        output_text='```json\n{"description": "Text.", "bullet_points": []}\n```'
    )
    original = _patched(transport)
    try:
        service = ContentGenerationService(api_key="sk-test")
        result = service.generate(ProductContentContext(name="Test"))
    finally:
        _restore(original)

    assert result.description == "Text."
