"""Conservative PDF validation before a document can enter the archive."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from xw_office.services.invoice_collection.errors import DocumentValidationError


@dataclass(frozen=True)
class PdfInspection:
    size_bytes: int
    page_count: int


def inspect_pdf(
    path: Path,
    *,
    max_bytes: int = 25 * 1024 * 1024,
    max_pages: int = 2_000,
) -> PdfInspection:
    """Validate a local artifact using signature, size and a real PDF parser."""
    try:
        if not path.is_file():
            raise DocumentValidationError("PDF-Datei fehlt")
        size = path.stat().st_size
        if size <= 0:
            raise DocumentValidationError("PDF-Datei ist leer")
        if size > max_bytes:
            raise DocumentValidationError("PDF-Datei überschreitet die zulässige Größe")
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise DocumentValidationError("Datei besitzt keine PDF-Signatur")
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise DocumentValidationError("Verschlüsselte PDFs benötigen eine manuelle Prüfung")
        pages = len(reader.pages)
        if pages <= 0:
            raise DocumentValidationError("PDF enthält keine Seiten")
        if pages > max_pages:
            raise DocumentValidationError("PDF überschreitet die zulässige Seitenzahl")
        return PdfInspection(size_bytes=size, page_count=pages)
    except DocumentValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - parser libraries expose varied exceptions
        raise DocumentValidationError("PDF konnte nicht sicher gelesen werden") from exc
