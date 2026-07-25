"""Shared German text normalization utilities.

Several modules need to compare German free text loosely (CRM duplicate
matching, Ausgaben-Check ignore rules, invoice/product search, unreleased
piece matching). Legacy code reimplemented umlaut handling and bank-purpose
cleanup slightly differently in each place; this module gives every caller
one shared implementation instead.
"""
from __future__ import annotations

import re
import unicodedata

_UMLAUT_MAP = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "Ä": "Ae",
    "Ö": "Oe",
    "Ü": "Ue",
}

_SEPA_MANDATE_REF = re.compile(r"\b(?:OG|FE)/\S+", re.IGNORECASE)
_IBAN_TOKEN = re.compile(r"\b[A-Za-z]{2}\d{2}[A-Za-z0-9]{10,30}\b")
_DATE_TOKEN = re.compile(r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\.?")
_TIME_TOKEN = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_german_text(value: str) -> str:
    """Lowercase, transliterate umlauts/ß, strip remaining diacritics and punctuation.

    Two spellings that only differ by umlaut style or case compare equal
    after this, e.g. "Müller" and "MUELLER" both become "mueller".
    """
    text = str(value or "")
    for source, target in _UMLAUT_MAP.items():
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def clean_bank_purpose(value: str) -> str:
    """Strip structured noise from an Austrian bank transaction purpose line.

    Removes SEPA mandate references (``OG/...``, ``FE/...``), IBAN-like
    tokens, and date/time stamps, so two occurrences of an otherwise
    identical recurring payment (e.g. a different invoice number each
    month) compare as similar text once fuzzy-matched.
    """
    text = str(value or "")
    text = _SEPA_MANDATE_REF.sub(" ", text)
    text = _IBAN_TOKEN.sub(" ", text)
    text = _DATE_TOKEN.sub(" ", text)
    text = _TIME_TOKEN.sub(" ", text)
    return " ".join(text.split())
