"""Prepare PLC customs documents for the calibrated A5 label printer."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import fitz


MM_TO_PT = 72.0 / 25.4
A5_WIDTH_MM = 148.0
A5_HEIGHT_MM = 210.0
BROTHER_UNPRINTABLE_MARGIN_MM = 4.23

# TEST AF: the previously preferred TEST-N geometry, proportionally reduced
# until it sits entirely inside the imageable area reported by the Brother
# HL-L5100DN driver. Windows-driver and application scaling both remain 100%.
AF_CONTENT_WIDTH_MM = A5_WIDTH_MM - (2 * BROTHER_UNPRINTABLE_MARGIN_MM)
AF_CONTENT_HEIGHT_MM = AF_CONTENT_WIDTH_MM * (206.0 / 144.0)
AF_TARGET_RECT = fitz.Rect(
    BROTHER_UNPRINTABLE_MARGIN_MM * MM_TO_PT,
    BROTHER_UNPRINTABLE_MARGIN_MM * MM_TO_PT,
    (BROTHER_UNPRINTABLE_MARGIN_MM + AF_CONTENT_WIDTH_MM) * MM_TO_PT,
    (BROTHER_UNPRINTABLE_MARGIN_MM + AF_CONTENT_HEIGHT_MM) * MM_TO_PT,
)

_A5_PAGE_RECT = fitz.Rect(0, 0, A5_WIDTH_MM * MM_TO_PT, A5_HEIGHT_MM * MM_TO_PT)
_PRINT_READY_MARKER = "XW-PLC-CUSTOMS-A5-AF"


class PlcCustomsDocumentError(ValueError):
    """Raised when a PLC customs PDF cannot be prepared safely."""


def build_customs_a5_print_pdf(pdf_bytes: bytes) -> bytes:
    """Return an A5/portrait print derivative using the calibrated AF layout.

    The original PLC PDF remains authoritative and must be archived separately.
    Every source page becomes one A5 page, so multi-page customs responses remain
    complete. A PLC-native A5 page is copied without the A4 content crop.
    """
    raw = bytes(pdf_bytes)
    if not raw.startswith(b"%PDF-"):
        raise PlcCustomsDocumentError("PLC-Zollformular ist kein gültiges PDF")

    try:
        source = fitz.open(stream=raw, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - PyMuPDF exposes several parser exceptions.
        raise PlcCustomsDocumentError(f"PLC-Zollformular kann nicht geöffnet werden: {exc}") from exc
    output = fitz.open()
    try:
        if source.page_count < 1:
            raise PlcCustomsDocumentError("PLC-Zollformular enthält keine Seite")
        if source.needs_pass:
            raise PlcCustomsDocumentError("PLC-Zollformular ist kennwortgeschützt")

        for source_page in source:
            target_page = output.new_page(width=_A5_PAGE_RECT.width, height=_A5_PAGE_RECT.height)
            if _is_a5_portrait(source_page.rect):
                target_page.show_pdf_page(
                    target_page.rect,
                    source,
                    source_page.number,
                    keep_proportion=False,
                    overlay=True,
                )
                continue

            content = _visible_content_bbox(source_page)
            rotation = 90 if content.width >= content.height else 0
            target_page.show_pdf_page(
                AF_TARGET_RECT,
                source,
                source_page.number,
                clip=content,
                rotate=rotation,
                keep_proportion=False,
                overlay=True,
            )

        output.set_metadata(
            {
                "title": "PLC Zollformular – A5 Druckfassung",
                "subject": "Kalibrierte Druckfassung; PLC-Original separat archiviert",
                "producer": _PRINT_READY_MARKER,
                "keywords": _PRINT_READY_MARKER,
            }
        )
        prepared = output.tobytes(garbage=4, deflate=True)
    except PlcCustomsDocumentError:
        raise
    except Exception as exc:  # noqa: BLE001 - preserve a user-facing recovery error.
        raise PlcCustomsDocumentError(f"A5-Druckfassung konnte nicht erstellt werden: {exc}") from exc
    finally:
        output.close()
        source.close()

    if not prepared.startswith(b"%PDF-"):
        raise PlcCustomsDocumentError("A5-Druckfassung ist kein gültiges PDF")
    return prepared


def customs_a5_print_path(source_path: str | Path) -> Path:
    """Return the persistent print-ready sibling path for one PLC original."""
    source = Path(source_path).expanduser().resolve()
    if source.parent.name.casefold() == "print_ready":
        return source
    return source.parent / "print_ready" / f"{source.stem} - A5.pdf"


def ensure_customs_a5_print_file(source_path: str | Path) -> Path:
    """Create or refresh the persistent A5 derivative for an archived PDF."""
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise PlcCustomsDocumentError(f"Archiviertes PLC-Zollformular fehlt: {source}")
    if _is_print_ready_file(source):
        return source

    target = customs_a5_print_path(source)
    if target.is_file() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns and _is_print_ready_file(target):
        return target

    prepared = build_customs_a5_print_pdf(source.read_bytes())
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".tmp") as handle:
        handle.write(prepared)
        temp_path = Path(handle.name)
    try:
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return target


def _visible_content_bbox(page: fitz.Page) -> fitz.Rect:
    content = fitz.Rect()
    for kind, coordinates in page.get_bboxlog():
        if not (str(kind).startswith("fill-") or str(kind).startswith("stroke-")):
            continue
        candidate = fitz.Rect(coordinates) & page.rect
        if candidate.is_empty or candidate.is_infinite:
            continue
        content |= candidate
    return content if not content.is_empty else page.rect


def _is_a5_portrait(rect: fitz.Rect) -> bool:
    width_mm = rect.width / MM_TO_PT
    height_mm = rect.height / MM_TO_PT
    return abs(width_mm - A5_WIDTH_MM) <= 1.0 and abs(height_mm - A5_HEIGHT_MM) <= 1.0


def _is_print_ready_file(path: Path) -> bool:
    try:
        document = fitz.open(path)
        try:
            if document.page_count < 1:
                return False
            metadata = document.metadata or {}
            marker = " ".join(str(metadata.get(key) or "") for key in ("producer", "keywords"))
            return _PRINT_READY_MARKER in marker and all(_is_a5_portrait(page.rect) for page in document)
        finally:
            document.close()
    except Exception:  # noqa: BLE001 - invalid legacy files must be regenerated.
        return False

