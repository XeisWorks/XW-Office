"""Deterministic, traversal-safe archive names."""
from __future__ import annotations

from datetime import date
import re
import unicodedata
from pathlib import Path

from xw_office.services.invoice_collection.domain import DocumentCandidate, ValidatedDocument


_INVALID = re.compile(r"[^A-Za-z0-9._-]+")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_component(value: str, *, fallback: str = "unknown", limit: int = 80) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    normalized = _INVALID.sub("-", normalized).strip(" .-")[:limit]
    if not normalized:
        normalized = fallback
    if normalized.upper() in _RESERVED:
        normalized = f"_{normalized}"
    return normalized


def build_relative_path(
    candidate: DocumentCandidate,
    *,
    sha256: str,
    fallback_date: date,
) -> Path:
    document_date = candidate.document_date or fallback_date
    provider = safe_component(candidate.connection.provider_id)
    tenant = safe_component(candidate.connection.tenant_id.value)
    account = safe_component(candidate.connection.account_alias)
    kind = safe_component(candidate.document_type.value)
    external = safe_component(candidate.external_id or sha256[:8], fallback=sha256[:8])
    filename = (
        f"{document_date:%Y-%m-%d}__{provider}__{account}__{kind}__"
        f"{external}__{sha256[:8]}.pdf"
    )
    return Path(tenant) / f"{document_date:%Y}" / f"{document_date:%m}" / provider / filename
