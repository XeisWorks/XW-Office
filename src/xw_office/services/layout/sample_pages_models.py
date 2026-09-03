"""Data contracts for exporting selected PDF pages as web-optimized JPG sample pages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_TARGET_HEIGHT_PX = 1000
DEFAULT_MAX_SIZE_KB = 200


class SamplePageExportError(Exception):
    """Invalid input, unreadable PDF, or rendering failure."""


@dataclass(frozen=True)
class SamplePageJob:
    """One source PDF plus the 1-based page numbers to export from it."""

    pdf_path: Path
    pages: tuple[int, ...]


@dataclass(frozen=True)
class SamplePageExportSettings:
    output_folder: Path
    target_height_px: int = DEFAULT_TARGET_HEIGHT_PX
    max_size_kb: int = DEFAULT_MAX_SIZE_KB


@dataclass(frozen=True)
class SamplePageExportResult:
    pdf_path: Path
    page_number: int
    output_path: Path
    quality_used: int
    file_size_bytes: int


def parse_page_numbers(raw: str, *, page_count: int) -> tuple[int, ...]:
    """Parse '1,5,7' or '1,5,8-10' (1-based, inclusive) into a sorted unique tuple."""
    text = str(raw or "").strip()
    if not text:
        raise SamplePageExportError("Bitte mindestens eine Seitenzahl angeben (z. B. 1,5,7).")

    pages: set[int] = set()
    for part in (p.strip() for p in text.split(",") if p.strip()):
        if "-" in part:
            start_raw, _, end_raw = part.partition("-")
            start_raw, end_raw = start_raw.strip(), end_raw.strip()
            if not (start_raw.isdigit() and end_raw.isdigit()):
                raise SamplePageExportError(f'Ungültiger Seitenbereich: "{part}".')
            start, end = int(start_raw), int(end_raw)
            if start > end:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            if not part.isdigit():
                raise SamplePageExportError(f'Ungültige Seitenzahl: "{part}".')
            pages.add(int(part))

    invalid = sorted(page for page in pages if page < 1 or page > page_count)
    if invalid:
        raise SamplePageExportError(
            f"Seite(n) {', '.join(str(p) for p in invalid)} liegen außerhalb von 1..{page_count}."
        )
    return tuple(sorted(pages))
