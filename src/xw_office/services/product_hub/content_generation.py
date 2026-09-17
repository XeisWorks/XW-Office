"""OpenAI-based description/bullet-point drafting for Product Hub products.

Mirrors the existing OpenAI call pattern already used elsewhere in this codebase
(``services/customer_aftercare/ai_classifier.py``, ``services/sendungen/service.py``):
raw ``httpx`` calls to the Responses API — no OpenAI SDK client anywhere in this repo
despite it being a ``pyproject.toml`` dependency, so a fresh SDK client here would be
inconsistent with everything else. Key comes from ``OPENAI_API_KEY`` via whatever
secret source the caller injects (the web service uses its own env-var-backed
``_EnvSecretSource``, same as Wix — see ``web/app.py``).

Generates a **draft only** — never writes to the database itself. The router layer
returns the draft for review; saving it is a separate, explicit PATCH
(``EditingService.update_product`` for the description,
``EditingService.set_bullet_points`` for the bullets) — same "never silently apply"
rule as every other AUTO_DRAFT content in this system (see the master-seed import's
own ``content_status`` convention).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

_DEFAULT_MODEL = "gpt-4.1-mini"
_TIMEOUT = 45.0
_MAX_BULLET_POINTS = 5

_SYSTEM_PROMPT = (
    "Du schreibst Produktbeschreibungen fuer XeisWorks, einen Musikverlag fuer "
    "Blasmusik-/Volksmusiknoten. Ton: freundlich, fachlich korrekt, deutschsprachig. "
    "Antworte ausschliesslich als JSON-Objekt mit den Feldern \"description\" "
    "(2-4 Saetze Fliesstext) und \"bullet_points\" (Liste aus bis zu "
    f"{_MAX_BULLET_POINTS} kurzen, konkreten Stichpunkten, z.B. Besetzung, "
    "Schwierigkeitsgrad, Stimmung, Format). Erfinde keine Fakten, die nicht aus den "
    "gegebenen Produktdaten hervorgehen oder allgemein fuer diese Art von Notenprodukt "
    "ueblich sind."
)


class ContentGenerationError(RuntimeError):
    """OpenAI call failed, or the API key isn't configured."""


@dataclass(frozen=True)
class ProductContentContext:
    """Everything the prompt is built from — only real, known product data, no
    invented facts (the schema also has no room for anything else)."""

    name: str
    category: str | None = None
    brand_name: str | None = None
    product_type: str | None = None
    existing_description: str | None = None
    music_attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratedContent:
    description: str
    bullet_points: list[str]


def _build_prompt(context: ProductContentContext) -> str:
    lines = [f"Produktname: {context.name}"]
    if context.category:
        lines.append(f"Kategorie: {context.category}")
    if context.brand_name:
        lines.append(f"Marke: {context.brand_name}")
    if context.product_type:
        lines.append(f"Produkttyp: {context.product_type}")
    for key, value in context.music_attributes.items():
        if value:
            lines.append(f"{key}: {value}")
    if context.existing_description:
        lines.append(f"Vorhandene Beschreibung (als Grundlage, gerne verbessern):\n{context.existing_description}")
    return "\n".join(lines)


def _response_text(payload: dict[str, Any]) -> str:
    text = str(payload.get("output_text") or "").strip()
    if text:
        return text
    output = payload.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                    value = str(block.get("text") or "").strip()
                    if value:
                        chunks.append(value)
        return "\n".join(chunks).strip()
    return ""


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ContentGenerationError("OpenAI Antwort leer")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContentGenerationError(f"OpenAI Antwort ist kein gueltiges JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ContentGenerationError("OpenAI Antwort ist kein JSON-Objekt")
    return data


class ContentGenerationService:
    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key

    def generate(self, context: ProductContentContext) -> GeneratedContent:
        if not self._api_key:
            raise ContentGenerationError("OPENAI_API_KEY ist nicht konfiguriert")

        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body = {
            "model": _DEFAULT_MODEL,
            "input": f"{_SYSTEM_PROMPT}\n\nProduktdaten:\n{_build_prompt(context)}",
            "max_output_tokens": 600,
        }
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.post(
                    "https://api.openai.com/v1/responses", headers=headers, json=body
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ContentGenerationError(f"OpenAI-Aufruf fehlgeschlagen: {exc}") from exc

        data = _parse_json_object(_response_text(payload))
        description = str(data.get("description") or "").strip()
        raw_bullets = data.get("bullet_points")
        bullet_points = (
            [str(b).strip() for b in raw_bullets if str(b).strip()][:_MAX_BULLET_POINTS]
            if isinstance(raw_bullets, list)
            else []
        )
        if not description:
            raise ContentGenerationError("OpenAI Antwort enthielt keine Beschreibung")
        return GeneratedContent(description=description, bullet_points=bullet_points)
