"""KI-Vorklassifikation von Lieferkorrektur-Mails (spec §3).

Mirrors the existing OpenAI integration in
:mod:`xw_office.services.sendungen.service` (direct ``httpx`` call against the
Responses API, no SDK) so the app has one consistent AI-integration pattern.
The AI only ever *suggests* — callers must route the result through the
review popup (spec §4) before anything becomes an active case. A failed or
unavailable AI call always falls back to a manual-review classification
rather than blocking case creation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4.1-mini"

#: The four confirmed case types from spec §2, plus UNKNOWN for
#: "Sonstiges / manuell prüfen" (spec §4's fifth dropdown option).
CASE_TYPES: tuple[str, ...] = (
    "B2B_WRONG_DELIVERY",
    "B2B_MISSING_ITEMS",
    "B2C_WRONG_DELIVERY",
    "B2B_CUSTOMER_ORDER_ERROR",
    "UNKNOWN",
)

_ERROR_PARTIES: tuple[str, ...] = ("xeisworks", "customer", "unknown")


@dataclass(frozen=True)
class AiExtractedItem:
    """One item mentioned in the mail (wrong-delivered or missing/owed)."""

    name: str = ""
    sku: str = ""
    quantity: str = "1"


@dataclass(frozen=True)
class AiClassification:
    """Result of classifying one Lieferkorrektur mail. Advisory only (spec §3)."""

    case_type: str
    confidence: float
    customer_name: str = ""
    customer_email: str = ""
    wix_order_number: str = ""
    error_party: str = "unknown"
    wrong_items: list[AiExtractedItem] = field(default_factory=list)
    missing_items: list[AiExtractedItem] = field(default_factory=list)
    courtesy_suggested: bool = True
    note: str = ""
    source: str = "fallback"

    def to_payload_json(self) -> str:
        """Serialize for ``CustomerAftercareCase.ai_payload_json`` (audit trail, spec §12/AI-02)."""
        return json.dumps(
            {
                "case_type": self.case_type,
                "confidence": self.confidence,
                "customer_name": self.customer_name,
                "customer_email": self.customer_email,
                "wix_order_number": self.wix_order_number,
                "error_party": self.error_party,
                "wrong_items": [item.__dict__ for item in self.wrong_items],
                "missing_items": [item.__dict__ for item in self.missing_items],
                "courtesy_suggested": self.courtesy_suggested,
                "note": self.note,
                "source": self.source,
            },
            ensure_ascii=False,
        )


def classify_mail(
    *,
    subject: str,
    sender: str,
    body_text: str,
    api_key: str | None,
) -> AiClassification:
    """Classify a Lieferkorrektur mail. Never raises — falls back to UNKNOWN on any failure."""
    if api_key:
        try:
            return _openai_classify(subject=subject, sender=sender, body_text=body_text, api_key=api_key)
        except Exception as exc:  # noqa: BLE001 - AI failure must never block PENDING_REVIEW creation.
            logger.warning("Lieferkorrektur-KI-Klassifikation fehlgeschlagen, nutze Fallback: %s", exc)
    return _fallback_classify(subject=subject, sender=sender, body_text=body_text)


def _openai_classify(*, subject: str, sender: str, body_text: str, api_key: str) -> AiClassification:
    prompt = (
        "Du analysierst eine Mail an den XeisWorks-Shop, die vermutlich eine "
        "Lieferkorrektur betrifft (falsch gelieferte oder fehlende Artikel). "
        "Bestimme den Falltyp und extrahiere die relevanten Angaben. "
        "Antworte ausschliesslich als JSON.\n\n"
        "Falltypen:\n"
        "- B2B_WRONG_DELIVERY: XeisWorks hat einem Haendler falsch geliefert "
        "(ein Artikel kam statt eines anderen).\n"
        "- B2B_MISSING_ITEMS: XeisWorks hat einem Haendler einen bestellten Artikel nicht geliefert.\n"
        "- B2C_WRONG_DELIVERY: XeisWorks hat einem Endkunden falsch geliefert.\n"
        "- B2B_CUSTOMER_ORDER_ERROR: Der Haendler hat sich selbst verklickt/falsch bestellt.\n"
        "- UNKNOWN: keiner der obigen Faelle trifft eindeutig zu, oder die Mail ist zu unklar.\n\n"
        "JSON-Schema:\n"
        "{\n"
        '  "case_type": "B2B_WRONG_DELIVERY|B2B_MISSING_ITEMS|B2C_WRONG_DELIVERY|'
        'B2B_CUSTOMER_ORDER_ERROR|UNKNOWN",\n'
        '  "confidence": 0.0,\n'
        '  "customer_name": "Name des Kunden/Haendlers oder leer",\n'
        '  "customer_email": "E-Mail-Adresse des Kunden oder leer",\n'
        '  "wix_order_number": "Ausgangsbestellnummer oder leer",\n'
        '  "error_party": "xeisworks|customer|unknown",\n'
        '  "wrong_items": [{"name": "Produktname", "sku": "optional", "quantity": "1"}],\n'
        '  "missing_items": [{"name": "Produktname", "sku": "optional", "quantity": "1"}],\n'
        '  "courtesy_suggested": true,\n'
        '  "note": "kurze deutsche Zusammenfassung fuer den Benutzer"\n'
        "}\n\n"
        f"Betreff: {subject}\n"
        f"Absender: {sender}\n"
        f"Mailinhalt:\n{body_text}"
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": _DEFAULT_MODEL, "input": prompt, "max_output_tokens": 900}
    with httpx.Client(timeout=45.0) as client:
        resp = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()
    data = _parse_json_object(_response_text(payload))
    case_type = str(data.get("case_type") or "").strip().upper()
    if case_type not in CASE_TYPES:
        case_type = "UNKNOWN"
    confidence = _normalize_confidence(data.get("confidence"))
    if case_type == "UNKNOWN":
        confidence = min(confidence, 0.0)
    error_party = str(data.get("error_party") or "unknown").strip().lower()
    if error_party not in _ERROR_PARTIES:
        error_party = "unknown"
    return AiClassification(
        case_type=case_type,
        confidence=confidence,
        customer_name=str(data.get("customer_name") or "").strip(),
        customer_email=str(data.get("customer_email") or "").strip(),
        wix_order_number=str(data.get("wix_order_number") or "").strip(),
        error_party=error_party,
        wrong_items=_normalize_items(data.get("wrong_items")),
        missing_items=_normalize_items(data.get("missing_items")),
        courtesy_suggested=_as_bool(data.get("courtesy_suggested"), default=True),
        note=str(data.get("note") or "").strip(),
        source="openai",
    )


def _fallback_classify(*, subject: str, sender: str, body_text: str) -> AiClassification:
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", sender)
    return AiClassification(
        case_type="UNKNOWN",
        confidence=0.0,
        customer_email=email_match.group(0) if email_match else "",
        courtesy_suggested=True,
        note="KI-Klassifikation nicht verfuegbar oder fehlgeschlagen — bitte manuell pruefen.",
        source="fallback",
    )


def _normalize_confidence(value: object) -> float:
    try:
        confidence = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _normalize_items(value: object) -> list[AiExtractedItem]:
    if not isinstance(value, list):
        return []
    items: list[AiExtractedItem] = []
    for entry in value:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            items.append(
                AiExtractedItem(
                    name=name,
                    sku=str(entry.get("sku") or "").strip(),
                    quantity=str(entry.get("quantity") or "1").strip() or "1",
                )
            )
        elif str(entry or "").strip():
            items.append(AiExtractedItem(name=str(entry).strip()))
    return items


def _as_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ja", "on"}
    return default


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
        raise RuntimeError("OpenAI Antwort leer")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError("OpenAI Antwort ist kein JSON-Objekt")
    return data
