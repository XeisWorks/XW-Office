"""Duplicate detection heuristics (rapidfuzz + rules)."""
from __future__ import annotations

from rapidfuzz import fuzz

from xw_studio.services.crm.types import ContactRecord, DuplicateCandidate, MatchReason


def contact_match_score(a: ContactRecord, b: ContactRecord) -> int:
    """Return 0..100 similarity score for two contacts."""
    name_score = fuzz.token_sort_ratio(a.name or "", b.name or "")
    email_match = (
        bool(a.email and b.email and a.email.lower() == b.email.lower())
    )
    phone_bonus = 0
    if a.phone and b.phone and _normalize_phone(a.phone) == _normalize_phone(b.phone):
        phone_bonus = 20
    city_bonus = 0
    if a.city and b.city and a.city.lower() == b.city.lower():
        city_bonus = 5
    # Same email is a strong duplicate signal: blend name similarity up (legacy sevDesk-style triage).
    if email_match:
        raw = int(name_score * 0.55 + 40 + phone_bonus + city_bonus)
    else:
        raw = int(name_score * 0.45 + phone_bonus + city_bonus)
    return max(0, min(100, raw))


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def classify_match_reason(a: ContactRecord, b: ContactRecord) -> MatchReason:
    """Named cascade step: prefer the strongest available signal.

    An exact, case-insensitive email match is the highest-confidence
    signal available on the current contact model (sevDesk's
    ``wixCustomerId`` custom field is not modeled yet — see
    :class:`~xw_studio.services.crm.types.ContactRecord`); everything else
    falls back to the fuzzy name/phone/city score.
    """
    if a.email and b.email and a.email.strip().casefold() == b.email.strip().casefold():
        return MatchReason.EMAIL_EXACT
    return MatchReason.FUZZY_NAME


def find_duplicate_candidates(
    contacts: list[ContactRecord],
    *,
    threshold: int = 75,
) -> list[DuplicateCandidate]:
    """O(n^2) pairwise scan — OK for modest CRM sizes; batch later."""
    out: list[DuplicateCandidate] = []
    for i, a in enumerate(contacts):
        for b in contacts[i + 1 :]:
            score = contact_match_score(a, b)
            if score >= threshold:
                out.append(
                    DuplicateCandidate(a=a, b=b, score=score, reason=classify_match_reason(a, b))
                )
    out.sort(key=lambda c: c.score, reverse=True)
    return out
