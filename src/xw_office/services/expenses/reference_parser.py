"""Deterministic presentation parsing for sevDesk bank text.

sevDesk exposes the original bank purpose as a single, provider-specific string.
This module derives a compact presentation projection without changing or
discarding the original fields.  The projection is deliberately conservative:
ambiguous merchant text is shown as a candidate and never treated as a fact in
the persistence layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from xw_office.core.text_normalize import normalize_german_text


_CARD_RE = re.compile(
    r"Bezahlung\s+Karte\b.*?\b\d{1,2}\.\d{1,2}\.\s*\d{1,2}:\d{2}"
    r"(?P<merchant>.*?)(?=\\+|SPESEN:|$)",
    re.IGNORECASE,
)
_FOREIGN_AMOUNT_RE = re.compile(
    r"\b(?P<amount>\d+(?:,\d{1,2})?)\s*(?P<currency>USD|GBP|CHF|EUR)\b",
    re.IGNORECASE,
)
_TECHNICAL_MARKER_RE = re.compile(r"\b(?:OG|FE)/\S+", re.IGNORECASE)
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ExpenseTextProjection:
    """Compact, UI-facing interpretation of one bank transaction text."""

    payee: str
    purpose: str
    source: str
    confidence: float
    merchant_key: str


_MERCHANT_ALIASES: tuple[tuple[str, str], ...] = (
    ("github inc", "GitHub Inc."),
    ("openai *chatgpt", "OpenAI"),
    ("msft *", "Microsoft"),
    ("google *google one", "Google One"),
    ("spotify", "Spotify"),
    ("scribd", "Scribd"),
    ("railway", "Railway"),
    ("uzr*neu-repro-online", "Neu-Repro Online"),
    ("apcoa airport graz", "APCOA Airport Graz"),
)


def _compact(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value or "").replace("\u00a0", " ")).strip()


def _title_unknown_merchant(value: str) -> str:
    text = _compact(value).replace("*", " ").strip(" .,*-/\\")
    text = re.sub(r"\b\d{2,}\b", "", text)
    text = _compact(text).strip(" .,*-/\\")
    if not text:
        return ""
    return text.title() if text.upper() == text else text


def _merchant_display(value: str) -> tuple[str, float]:
    text = _compact(value)
    normalized = normalize_german_text(text)
    for key, display in _MERCHANT_ALIASES:
        if normalized.startswith(normalize_german_text(key)):
            return display, 0.98
    if normalized.startswith("paypal"):
        display = _title_unknown_merchant(re.sub(r"^PAYPAL[_* ]*", "", text, flags=re.IGNORECASE))
        return display or "PayPal", 0.75
    # A card descriptor is structurally reliable, but a previously unseen
    # merchant name is still only a candidate until a user confirms it.
    display = _title_unknown_merchant(text)
    return display, 0.78 if display else 0.0


def _card_projection(text: str) -> ExpenseTextProjection | None:
    match = _CARD_RE.search(text)
    if match is None:
        return None
    merchant, merchant_confidence = _merchant_display(match.group("merchant"))
    amount = _FOREIGN_AMOUNT_RE.search(text)
    if amount is not None:
        purpose = (
            f"Online-Kartenzahlung · {amount.group('amount')} "
            f"{amount.group('currency').upper()}"
        )
    else:
        purpose = "Kartenzahlung"
    if not merchant:
        merchant = "Kartenzahlung"
        purpose = "Kartenzahlung"
    return ExpenseTextProjection(
        payee=merchant,
        purpose=purpose,
        source="card_descriptor",
        confidence=merchant_confidence,
        merchant_key=normalize_german_text(merchant),
    )


def _meaningful_prefix(text: str) -> str:
    """Return the human reference before SEPA metadata, if it is meaningful."""
    prefix = _TECHNICAL_MARKER_RE.split(text, maxsplit=1)[0]
    prefix = _IBAN_RE.sub(" ", prefix)
    prefix = _compact(prefix).strip(" /-")
    if not prefix or not re.search(r"[A-Za-zÄÖÜäöüß]", prefix):
        return ""
    # These are usually mandate/account identifiers, not a useful purpose.
    if re.fullmatch(r"[A-Z0-9 /.-]+", prefix, re.IGNORECASE) and not re.search(
        r"[A-ZÄÖÜäöüß]{3,}", prefix
    ):
        return ""
    return prefix


def _purpose_projection(text: str, payee: str) -> tuple[str, str, float]:
    source = _compact(text)
    if not source:
        return "—", "fallback", 0.0

    card = _card_projection(source)
    if card is not None:
        # sevDesk occasionally supplies a payee as well as a card descriptor;
        # keep the official payee but retain the compact card purpose.
        return card.purpose, card.source, card.confidence

    match = re.match(r"A1\s+RECHNUNG\s+(\d{1,2}/\d{2})", source, re.IGNORECASE)
    if match:
        return f"Rechnung {match.group(1)}", "reference_rule", 0.99

    match = re.match(r"Lohn\s+(\d{2}/\d{2})", source, re.IGNORECASE)
    if match:
        return f"Lohn {match.group(1)}", "reference_rule", 0.99

    match = re.match(r"Vorschreib\.\s+(.+?)(?=OG/|$)", source, re.IGNORECASE)
    if match:
        return f"Vorschreibung {_compact(match.group(1))}", "reference_rule", 0.95

    match = re.match(r"Beitr\.KtoNr\.?\s*:\s*(\S+)", source, re.IGNORECASE)
    if match:
        return f"Beitragskonto {match.group(1)}", "reference_rule", 0.98

    match = re.match(
        r"SEPA-Lastschrift\s+\S+\s+(?P<label>[A-Za-zÄÖÜäöüß]{3,}(?:\s+[A-Za-zÄÖÜäöüß]+)*)\s+OG/",
        source,
        re.IGNORECASE,
    )
    if match:
        return f"Lastschrift · {_compact(match.group('label'))}", "reference_rule", 0.91
    if re.match(r"SEPA-Lastschrift\b", source, re.IGNORECASE):
        return "Lastschrift", "reference_rule", 0.88

    match = re.match(r"(\d{3}-\d{7}-\d{7})\s+AMZN(?:Business| Mktp)", source, re.IGNORECASE)
    if match:
        return f"Bestellung {match.group(1)}", "reference_rule", 0.97

    match = re.match(r"Abbuchung Einzugserm(?:ä|ae)chtigung\s+(\d+)", source, re.IGNORECASE)
    if match:
        return f"Lastschrift {match.group(1)}", "reference_rule", 0.94

    if re.match(r"\d+\/PAYPAL\b", source, re.IGNORECASE):
        return "PayPal-Zahlung", "reference_rule", 0.9

    match = re.match(r"(?P<reference>[A-Z]{2}\d{2}-\d+)\b", source, re.IGNORECASE)
    if match:
        return f"Referenz {match.group('reference').upper()}", "reference_rule", 0.86

    prefix = _meaningful_prefix(source)
    if prefix:
        # Do not repeat the official payee as a second, noisy purpose value.
        if payee and normalize_german_text(prefix) == normalize_german_text(payee):
            return "—", "fallback", 0.9
        return prefix, "purpose_prefix", 0.82

    return "—", "fallback", 0.55 if payee else 0.0


def project_expense_text(
    *, payee_name: str, payment_reference: str, purpose: str
) -> ExpenseTextProjection:
    """Create a compact presentation projection from original sevDesk fields."""
    official_payee = _compact(payee_name)
    source_text = _compact(payment_reference) or _compact(purpose)
    card = _card_projection(source_text)
    if card is not None and not official_payee:
        return card

    payee = official_payee or (card.payee if card is not None else "—")
    purpose_text, source, confidence = _purpose_projection(source_text, payee)
    if card is not None:
        source = card.source
        confidence = min(confidence or 1.0, card.confidence or 1.0)
    return ExpenseTextProjection(
        payee=payee,
        purpose=purpose_text,
        source=source,
        confidence=confidence,
        merchant_key=normalize_german_text(payee),
    )


def format_expense_original_details(
    *,
    raw_payee: str,
    raw_payment_reference: str,
    raw_purpose: str,
    source: str,
    confidence: float,
) -> str:
    """Build a tooltip that keeps the audit trail available on demand."""
    lines = [f"Erkennung: {source or 'unbekannt'} ({confidence:.0%})"]
    if raw_payee.strip():
        lines.append(f"Original-Empfänger: {raw_payee.strip()}")
    if raw_payment_reference.strip():
        lines.append(f"Original-Zahlungsreferenz: {raw_payment_reference.strip()}")
    if raw_purpose.strip():
        lines.append(f"Original-Verwendungszweck: {raw_purpose.strip()}")
    return "\n".join(lines)
