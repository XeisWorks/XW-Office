"""Local paths and redaction helpers for invoice collection."""
from __future__ import annotations

import csv
import io
import os
import re
import subprocess
from pathlib import Path

from xw_office.core.app_paths import invoice_collection_dir, local_app_data_root


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
    _apply_windows_private_acl(root)
    return directories


_WINDOWS_SID_RE = re.compile(r"S-1-\d+(?:-\d+)+\Z")


def _apply_windows_private_acl(path: Path) -> None:
    """Restrict local collector state to the current user, SYSTEM and administrators."""
    if os.name != "nt":
        return
    sid = _current_windows_user_sid()
    command = [
        "icacls.exe",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"*{sid}:(OI)(CI)F",
        "*S-1-5-18:(OI)(CI)F",
        "*S-1-5-32-544:(OI)(CI)F",
        "/T",
        "/C",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        raise RuntimeError("Could not secure invoice collection directory permissions") from None
    if result.returncode != 0:
        raise RuntimeError("Could not secure invoice collection directory permissions")


def _current_windows_user_sid() -> str:
    """Read the current SID from whoami CSV output without retaining the account name."""
    try:
        result = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        raise RuntimeError("Could not determine current Windows user permissions") from None
    if result.returncode != 0:
        raise RuntimeError("Could not determine current Windows user permissions")
    for row in csv.reader(io.StringIO(result.stdout.lstrip("\ufeff"))):
        for value in row:
            sid = value.strip()
            if _WINDOWS_SID_RE.fullmatch(sid):
                return sid
    raise RuntimeError("Could not determine current Windows user permissions")


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
    local_root = local_app_data_root().resolve(strict=False)
    try:
        resolved.relative_to(local_root)
    except ValueError as exc:
        raise ValueError(
            "invoice collection sensitive state must stay under local app data"
        ) from exc
