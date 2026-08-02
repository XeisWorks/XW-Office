"""Windows-safe filename sanitizing for QR-code output files."""
from __future__ import annotations

import re

from xw_office.services.qr_codes.models import QrConfigurationError

WINDOWS_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
_RESERVED_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def sanitize_windows_filename(value: str, replacement: str = "_") -> str:
    """Replace characters Windows forbids in filenames; keep the logical id untouched.

    The logical id (e.g. "UUU#2-POS/01") is never mutated elsewhere - only this
    function's output is used as an actual filename.
    """
    cleaned = WINDOWS_INVALID_FILENAME_CHARS.sub(replacement, value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(f"{re.escape(replacement)}+", replacement, cleaned)

    if not cleaned:
        raise QrConfigurationError("Der Dateiname ist nach der Bereinigung leer.")

    stem_upper = cleaned.split(".", 1)[0].upper()
    if stem_upper in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    return cleaned
