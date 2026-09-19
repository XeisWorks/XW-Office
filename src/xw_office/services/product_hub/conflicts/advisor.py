"""Read-only OpenAI advisor for already detected Product Hub conflicts.

The model receives a small conflict snapshot and may explain or recommend, but it
has no tools and no path to the decision/apply services.  Its result is a draft for
the user, never a resolution.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

_DEFAULT_MODEL = "gpt-4.1-mini"
_TIMEOUT = 45.0

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "explanation": {"type": "string"},
        "likely_causes": {"type": "array", "items": {"type": "string"}},
        "recommendation": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title",
        "explanation",
        "likely_causes",
        "recommendation",
        "next_steps",
        "confidence",
        "warnings",
        "evidence",
    ],
}

_INSTRUCTIONS = """Du bist ein vorsichtiger Assistent fuer den internen XeisWorks Product Hub.
Erklaere den vorliegenden Sync-Konflikt in einfachem Deutsch fuer einen Anfaenger.
Nutze ausschliesslich die gelieferten Fakten. Behaupte insbesondere nicht, ein externes
Produkt sei geloescht, wenn nur ein fehlgeschlagener Abruf belegt ist. Nenne Unsicherheit
klar, zitiere konkrete Quellwerte im Feld evidence und empfehle nur sichere, manuelle
Pruefschritte. Triff keine Entscheidung und fordere niemals eine automatische Aenderung,
einen externen Write oder eine kritische Zusammenfuehrung."""


class ConflictAdviceError(RuntimeError):
    """The optional AI advice could not be generated."""


@dataclass(frozen=True)
class ConflictAdvice:
    title: str
    explanation: str
    likely_causes: list[str]
    recommendation: str
    next_steps: list[str]
    confidence: str
    warnings: list[str]
    evidence: list[str]


def _response_text(payload: dict[str, Any]) -> str:
    direct = str(payload.get("output_text") or "").strip()
    if direct:
        return direct
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                value = str(block.get("text") or "").strip()
                if value:
                    chunks.append(value)
    return "\n".join(chunks).strip()


def _parse_payload(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConflictAdviceError("OpenAI-Antwort war kein gueltiges JSON") from exc
    if not isinstance(result, dict):
        raise ConflictAdviceError("OpenAI-Antwort war kein JSON-Objekt")
    return result


class ConflictAdviceService:
    def __init__(self, *, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        self._api_key = api_key
        self._model = model

    def advise(self, snapshot: dict[str, Any]) -> ConflictAdvice:
        if not self._api_key:
            raise ConflictAdviceError("OPENAI_API_KEY ist nicht konfiguriert")
        body = {
            "model": self._model,
            "store": False,
            "instructions": _INSTRUCTIONS,
            "input": "Konfliktdaten:\n" + json.dumps(snapshot, ensure_ascii=False, default=str),
            "max_output_tokens": 900,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "product_hub_conflict_advice",
                    "strict": True,
                    "schema": _SCHEMA,
                }
            },
        }
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ConflictAdviceError(f"OpenAI-Aufruf fehlgeschlagen: {exc}") from exc

        raw = _response_text(payload)
        if not raw:
            raise ConflictAdviceError("OpenAI-Antwort war leer")
        data = _parse_payload(raw)
        return ConflictAdvice(
            title=str(data.get("title") or "KI-Einschaetzung").strip(),
            explanation=str(data.get("explanation") or "").strip(),
            likely_causes=_strings(data.get("likely_causes")),
            recommendation=str(data.get("recommendation") or "").strip(),
            next_steps=_strings(data.get("next_steps")),
            confidence=str(data.get("confidence") or "low"),
            warnings=_strings(data.get("warnings")),
            evidence=_strings(data.get("evidence")),
        )


def _strings(value: object) -> list[str]:
    return (
        [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, list)
        else []
    )
