"""Deterministic, traversal-safe archive names."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from xw_office.services.invoice_collection.domain import DocumentCandidate


_INVALID = re.compile(r"[^A-Za-z0-9._-]+")
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_component(value: str, *, fallback: str = "unknown", limit: int = 80) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    normalized = _INVALID.sub("-", normalized).strip(" .-")[:limit]
    if not normalized:
        normalized = fallback
    if normalized.split(".", 1)[0].upper() in _RESERVED:
        normalized = f"_{normalized}"
    return normalized


def workspace_download_path(workspace: Path, original_filename: str) -> Path:
    """Map an untrusted provider filename to one safe file inside its temp workspace."""
    root = workspace.resolve()
    filename = safe_component(original_filename, fallback="attachment.pdf")
    destination = (root / filename).resolve()
    if destination.parent != root:
        raise ValueError("download filename escaped its workspace")
    return destination


def build_relative_path(
    candidate: DocumentCandidate,
    *,
    sha256: str,
) -> Path:
    provider = safe_component(candidate.connection.provider_id)
    tenant = safe_component(candidate.connection.tenant_id.value)
    account = safe_component(candidate.connection.account_alias)
    kind = safe_component(candidate.document_type.value)
    external = safe_component(candidate.external_id or sha256[:8], fallback=sha256[:8])
    document_date = candidate.document_date
    date_prefix = document_date.isoformat() if document_date else "date-unknown"
    filename = f"{date_prefix}__{provider}__{account}__{kind}__{external}__{sha256[:8]}.pdf"
    if candidate.metadata.get("review_reason"):
        return Path(tenant) / "_needs_review" / provider / filename
    if document_date is None:
        raise ValueError("document without date must be marked for review")
    return Path(tenant) / f"{document_date:%Y}" / f"{document_date:%m}" / provider / filename
