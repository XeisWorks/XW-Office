from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from xw_office.services.product_hub.conflicts.advisor import (
    ConflictAdviceError,
    ConflictAdviceService,
    find_wix_mapping_candidates,
)
from xw_office.services.wix.client import WixProduct, WixProductVariant
from xw_office.web.routers.conflicts import (
    _fallback_advice,
    _sanitize_wix_description,
    _wix_variant_matches,
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


def test_mapping_candidates_prefer_exact_sku_and_exclude_broken_id() -> None:
    candidates = find_wix_mapping_candidates(
        [
            WixProduct(id="broken", name="Altes Produkt", sku="XW-1"),
            WixProduct(id="replacement", name="Testprodukt", sku="XW-1"),
            WixProduct(id="similar", name="Testprodukt Deluxe", sku="XW-99"),
        ],
        product_name="Testprodukt",
        product_sku="XW-1",
        current_external_id="product_broken",
    )

    assert candidates[0].external_id == "replacement"
    assert candidates[0].score == 100
    assert "Exakte SKU" in candidates[0].match_reasons
    assert all(candidate.external_id != "broken" for candidate in candidates)


def test_mapping_candidates_exclude_name_only_or_sku_only_near_matches() -> None:
    candidates = find_wix_mapping_candidates(
        [
            WixProduct(id="name-only", name="Testprodukt Deluxe", sku="OTHER-1"),
            WixProduct(id="sku-only", name="Unverwandter Artikel", sku="XW-9"),
        ],
        product_name="Testprodukt",
        product_sku="XW-1",
    )

    assert candidates == []


def test_mapping_candidates_include_format_sku_variants() -> None:
    candidates = find_wix_mapping_candidates(
        [WixProduct(id="digital", name="Volksmusik #1 - Horn 1 in F", sku="XW-101.3-D")],
        product_name="Volksmusik #1 - Horn 1 in F",
        product_sku="XW-101.3",
    )

    assert candidates[0].external_id == "digital"
    assert candidates[0].score == 100
    assert "SKU-Variante" in candidates[0].match_reasons


def test_mapping_candidates_match_a_wix_variant_sku_to_its_parent_product() -> None:
    candidates = find_wix_mapping_candidates(
        [
            WixProduct(
                id="bh-polka",
                name="BH Polka",
                skus=["XW-6012", "XW-6212", "XW-6601"],
            )
        ],
        product_name="BH-Polka [Kleine Besetzung]",
        product_sku="XW-6012",
    )

    assert candidates[0].external_id == "bh-polka"
    assert candidates[0].sku == "XW-6012"
    assert candidates[0].score == 100
    assert "Exakte SKU" in candidates[0].match_reasons


def test_mapping_candidate_carries_the_exact_wix_variant_and_its_name() -> None:
    candidates = find_wix_mapping_candidates(
        [
            WixProduct(
                id="bh-polka",
                name="BH Polka",
                skus=["XW-6012"],
                variants=[
                    WixProductVariant(
                        id="wix-small",
                        sku="XW-6012",
                        name="Besetzung: Kleine Besetzung",
                    )
                ],
            )
        ],
        product_name="BH-Polka [Kleine Besetzung]",
        product_sku="XW-6012",
    )

    assert candidates[0].external_id == "bh-polka"
    assert candidates[0].variant_external_id == "wix-small"
    assert candidates[0].variant_name == "Besetzung: Kleine Besetzung"


def test_wix_variant_verification_requires_matching_id_and_hub_sku() -> None:
    raw = {
        "variants": [
            {
                "id": "wix-small",
                "variant": {"sku": "XW-6012"},
            }
        ]
    }

    assert _wix_variant_matches(raw, "wix-small", "XW-6012")
    assert not _wix_variant_matches(raw, "wix-small", "XW-6212")
    assert not _wix_variant_matches(raw, "other-variant", "XW-6012")


def test_fallback_advice_keeps_mapping_candidates_usable_without_ai() -> None:
    result = _fallback_advice(
        {
            "conflict": {"type": "WRONG_PRODUCT_MAPPING"},
            "mapping_lookup": {"candidates": [{"external_id": "wix-1"}]},
        }
    )

    assert result.confidence == "medium"
    assert "SKU" in result.recommendation
    assert "KI-Einschätzung" in result.warnings[0]


def test_wix_description_keeps_safe_formatting_and_removes_active_content() -> None:
    description = _sanitize_wix_description(
        '<p><strong>Alpenmusik</strong></p><script>alert("x")</script><img src=x onerror=bad()>'
    )

    assert description == "<p><strong>Alpenmusik</strong></p>"
