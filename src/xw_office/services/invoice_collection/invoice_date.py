"""Conservative extraction of explicitly labeled invoice dates from text PDFs."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re

from pypdf import PdfReader


_DATE = r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{4})"
_LABELED_DATE = re.compile(
    rf"(?:rechnungsdatum|datum\s+der\s+rechnung|rechnung\s+vom|"
    rf"invoice\s+date|date\s+of\s+invoice|issued\s+on)\s*[:#-]?\s*{_DATE}",
    re.IGNORECASE,
)


def extract_invoice_date_from_text(text: str) -> date | None:
    """Return a date only when exactly one explicit invoice-date label is found."""
    found: set[date] = set()
    for match in _LABELED_DATE.finditer(text):
        parsed = _parse_date(match.group(1))
        if parsed is not None:
            found.add(parsed)
    return next(iter(found)) if len(found) == 1 else None


def extract_invoice_date_from_pdf(path: Path, *, max_pages: int = 3) -> date | None:
    """Inspect only the first few text pages; OCR and heuristic unlabeled dates are excluded."""
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            return None
        text = "\n".join(page.extract_text() or "" for page in reader.pages[:max_pages])
    except Exception:  # noqa: BLE001 - unreadable metadata stays unknown and requires review
        return None
    return extract_invoice_date_from_text(text)


def _parse_date(value: str) -> date | None:
    formats = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y")
    for date_format in formats:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None
