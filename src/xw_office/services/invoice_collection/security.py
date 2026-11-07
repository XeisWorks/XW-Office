"""Local paths and redaction helpers for invoice collection."""
from __future__ import annotations

import re
from pathlib import Path

from xw_office.core.app_paths import invoice_collection_dir


def ensure_invoice_collection_dirs() -> dict[str, Path]:
    """Create local-only directories and return their paths."""
    root = invoice_collection_dir()
    directories = {
        "root": root,
        "profiles": root / "profiles",
        "auth": root / "auth",
        "journal": root / "journal",
        "tmp": root / "tmp",
        "quarantine": root / "quarantine",
    }
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True)
    return directories


_AUTH_RE = re.compile(r"(?i)\b(authorization\s*:\s*)bearer\s+[^\s,;\"']+")
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?token|api[_-]?key|password|secret|cookie)"
    r"(\s*[:=]\s*)([^\s,;\"']{3,})"
)


def redact_sensitive_text(value: str) -> str:
    """Redact common secret-bearing key/value pairs before logging or displaying."""
    redacted = _AUTH_RE.sub(r"\1***redacted***", str(value or ""))
    return _SECRET_RE.sub(r"\1\2***redacted***", redacted)


def assert_local_path(path: Path) -> None:
    """Reject repository or OneDrive paths for machine-local sensitive state."""
    resolved = path.expanduser().resolve(strict=False)
    local_root = invoice_collection_dir().resolve(strict=False)
    try:
        resolved.relative_to(local_root)
    except ValueError as exc:
        raise ValueError("invoice collection sensitive state must stay under local app data") from exc
