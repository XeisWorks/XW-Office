"""Read-only OpenAI advisor for already detected Product Hub conflicts.

The model receives a small conflict snapshot and may explain or recommend, but it
has no tools and no path to the decision/apply services.  Its result is a draft for
the user, never a resolution.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx
from rapidfuzz import fuzz

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
Erklaere den vorliegenden Sync-Konflikt in einfachem Deutsch fuer einen Anfaenger, aber
maximal kompakt: title hoechstens 8 Woerter, explanation und recommendation jeweils
hoechstens zwei kurze Saetze, next_steps hoechstens zwei kurze Punkte. Wiederhole keine
IDs oder Vergleichsdaten, die bereits in der Oberflaeche dargestellt werden.
Nutze ausschliesslich die gelieferten Fakten. Behaupte insbesondere nicht, ein externes
Produkt sei geloescht, wenn nur ein fehlgeschlagener Abruf belegt ist. Bei mapping_lookup
musst du die Kandidaten nach exakter SKU, exaktem Namen und dann Namensnaehe bewerten.
Eine SKU-Variante mit Format-Suffix wie -D ist ein moeglicher, aber nicht identischer
Kandidat: weise darauf hin, dass Produkttyp und Ausgabe vor dem Mapping zu pruefen sind.
Wenn ein Kandidat mit hoher Uebereinstimmung vorhanden ist, nenne genau seinen Namen,
seine SKU und seine ID und formuliere als naechste Handlung: Kandidat in Wix pruefen und
danach das Mapping gezielt uebernehmen. Wenn kein Kandidat gefunden wurde, empfehle nicht,
blind weitere IDs zu probieren, sondern zuerst Berechtigung/Verbindung und danach eine
manuelle Suche nach SKU und Produktname. Nenne Unsicherheit klar, zitiere konkrete
Quellwerte im Feld evidence und empfehle nur sichere, manuelle Pruefschritte. Triff keine
Entscheidung und fordere niemals eine automatische Aenderung, einen externen Write oder
eine kritische Zusammenfuehrung."""


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


@dataclass(frozen=True)
class WixMappingCandidate:
    """A read-only, ranked Wix product suggestion for a broken mapping."""

    external_id: str
    name: str
    sku: str
    score: int
    match_reasons: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "external_id": self.external_id,
            "name": self.name,
            "sku": self.sku,
            "score": self.score,
            "match_reasons": list(self.match_reasons),
        }


def _search_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in text).split())


def _canonical_id(value: object) -> str:
    return str(value or "").strip().removeprefix("product_").casefold()


def _is_sku_variant(first: str, second: str) -> bool:
    """Return whether two SKUs differ only by a format-style suffix (for example -D)."""
    first = re.sub(r"\s+", "", str(first or "").casefold())
    second = re.sub(r"\s+", "", str(second or "").casefold())
    if not first or not second or first == second:
        return False
    shorter, longer = sorted((first, second), key=len)
    return (
        longer.startswith(shorter) and len(longer) > len(shorter) and longer[len(shorter)] in "-_/."
    )


def find_wix_mapping_candidates(
    products: list[object],
    *,
    product_name: str,
    product_sku: str,
    current_external_id: str = "",
    limit: int = 3,
) -> list[WixMappingCandidate]:
    """Rank likely replacements without ever deciding or changing a mapping.

    Exact SKU/name matches are preferred. Fuzzy matches must corroborate both
    SKU and name, so unrelated products are never presented as a likely fix.
    """
    name = _search_text(product_name)
    sku = _search_text(product_sku)
    current_id = _canonical_id(current_external_id)
    ranked: list[WixMappingCandidate] = []
    seen: set[str] = set()
    for row in products:
        external_id = str(getattr(row, "id", "") or "").strip()
        canonical = _canonical_id(external_id)
        if not canonical or canonical == current_id or canonical in seen:
            continue
        candidate_name = str(getattr(row, "name", "") or "").strip()
        candidate_sku = str(getattr(row, "sku", "") or "").strip()
        candidate_name_normalized = _search_text(candidate_name)
        candidate_sku_normalized = _search_text(candidate_sku)
        reasons: list[str] = []
        scores: list[float] = []
        exact_sku = bool(sku and candidate_sku_normalized == sku)
        exact_name = bool(name and candidate_name_normalized == name)
        sku_score = (
            fuzz.ratio(sku, candidate_sku_normalized) if sku and candidate_sku_normalized else 0.0
        )
        name_score = (
            fuzz.WRatio(name, candidate_name_normalized)
            if name and candidate_name_normalized
            else 0.0
        )
        if exact_sku:
            reasons.append("Exakte SKU")
            scores.append(100.0)
        elif _is_sku_variant(product_sku, candidate_sku):
            reasons.append("SKU-Variante")
            scores.append(94.0)
        if exact_name:
            reasons.append("Exakter Produktname")
            scores.append(100.0)
        elif reasons and name_score >= 70:
            reasons.append(f"Ähnlicher Produktname ({round(name_score)} %)")
        if not reasons and sku_score >= 85 and name_score >= 78:
            reasons.extend(
                [
                    f"Ähnliche SKU ({round(sku_score)} %)",
                    f"Ähnlicher Produktname ({round(name_score)} %)",
                ]
            )
            scores.extend([sku_score, name_score])
        if not reasons:
            continue
        seen.add(canonical)
        ranked.append(
            WixMappingCandidate(
                external_id=external_id,
                name=candidate_name,
                sku=candidate_sku,
                score=max(0, min(100, round(max(scores)))),
                match_reasons=reasons,
            )
        )
    ranked.sort(
        key=lambda candidate: (-candidate.score, candidate.name.casefold(), candidate.external_id)
    )
    return ranked[: max(1, limit)]


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
            "max_output_tokens": 350,
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
