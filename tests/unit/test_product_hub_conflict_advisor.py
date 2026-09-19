from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from xw_office.services.product_hub.conflicts.advisor import (
    ConflictAdviceError,
    ConflictAdviceService,
)


def test_advisor_uses_strict_stateless_output_without_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    answer = {
        "title": "Wix-Verknüpfung prüfen",
        "explanation": "Der Abruf ist fehlgeschlagen.",
        "likely_causes": ["Die ID könnte veraltet sein."],
        "recommendation": "Zuerst erneut prüfen.",
        "next_steps": ["Wix erneut prüfen"],
        "confidence": "low",
        "warnings": ["Nichts automatisch ändern."],
        "evidence": ["Wix: state=not_found"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"output_text": json.dumps(answer)})

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = ConflictAdviceService(api_key="test-key").advise(
        {"product": {"sku": "XW-1"}, "conflict": {"type": "WRONG_PRODUCT_MAPPING"}}
    )

    assert result.recommendation == "Zuerst erneut prüfen."
    assert captured["store"] is False
    assert captured["text"]["format"]["strict"] is True
    assert captured["text"]["format"]["type"] == "json_schema"
    assert "tools" not in captured


def test_advisor_fails_cleanly_without_api_key() -> None:
    with pytest.raises(ConflictAdviceError, match="OPENAI_API_KEY"):
        ConflictAdviceService(api_key="").advise({})
