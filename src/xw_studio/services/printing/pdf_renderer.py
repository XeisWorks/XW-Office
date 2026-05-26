"""Render PDF pages to a QPrinter via PyMuPDF (high-DPI raster path)."""
from __future__ import annotations

import logging

import fitz  # PyMuPDF
from PySide6.QtCore import QPointF, QMarginsF
from PySide6.QtGui import QImage, QPainter, QPageSize, QPageLayout
from PySide6.QtPrintSupport import QPrinter

logger = logging.getLogger(__name__)

MUSIC_DPI = 600
INVOICE_DPI = 300


def _expand_ranges(page_ranges: list[range], page_count: int) -> list[int]:
    pages: list[int] = []
    for pr in page_ranges:
        for p in pr:
            if 0 <= p < page_count and p not in pages:
                pages.append(p)
    return pages


def page_indices_from_qprinter(printer: QPrinter, page_count: int) -> list[int] | None:
    """Map Qt print dialog page range to 0-based indices.

    Returns ``None`` to print all pages. Clamps to *page_count*.
    """
    if page_count <= 0:
        return None
    pr_range = printer.printRange()
    if pr_range == QPrinter.PrintRange.AllPages:
        return None
    if pr_range == QPrinter.PrintRange.Selection:
        return None
    if pr_range != QPrinter.PrintRange.PageRange:
        return None

    start = int(printer.fromPage())
    end = int(printer.toPage())
    if start < 1 or end < 1:
        return None
    lo = max(0, start - 1)
    hi_excl = min(page_count, end)
    if lo >= hi_excl:
        return None
    return list(range(lo, hi_excl))


def _duplex_mode(value: str) -> QPrinter.DuplexMode | None:
    normalized = str(value or "").strip().casefold().replace("_", "").replace("-", "")
    if normalized in {"", "default", "driver"}:
        return None
    if normalized in {"simplex", "none", "off"}:
        return QPrinter.DuplexMode.DuplexNone
    if normalized in {"long", "longedge", "duplex", "duplexlong", "duplexlongedge"}:
        return QPrinter.DuplexMode.DuplexLongSide
    if normalized in {"short", "shortedge", "duplexshort", "duplexshortedge"}:
        return QPrinter.DuplexMode.DuplexShortSide
    logger.warning("Unknown duplex mode %r; using printer default", value)
    return None


def _configure_printer_for_a4_portrait(
    printer: QPrinter,
    *,
    dpi: int,
    duplex: str = "",
) -> None:
    printer.setResolution(int(dpi))
    layout = QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4),
        QPageLayout.Orientation.Portrait,
        QMarginsF(0.0, 0.0, 0.0, 0.0),
        QPageLayout.Unit.Millimeter,
    )
    printer.setPageLayout(layout)
    printer.setFullPage(True)
    mode = _duplex_mode(duplex)
    if mode is not None:
        printer.setDuplex(mode)


def print_pdf(
    pdf_path: str,
    printer: QPrinter,
    dpi: int = MUSIC_DPI,
    *,
    pages: list[int] | None = None,
    page_ranges: list[range] | None = None,
    duplex: str = "",
) -> None:
    """Print *pdf_path* using *printer*, rasterizing each page at *dpi*.

    *pages*: explicit 0-based page indices. If set, *page_ranges* is ignored.
    *page_ranges*: legacy alternative; merged only when *pages* is ``None``.
    If both are ``None``, all PDF pages are printed.

    Music scores should use :data:`MUSIC_DPI` (600); invoices often use
    :data:`INVOICE_DPI` (300).
    """
    doc = fitz.open(pdf_path)
    try:
        pc = len(doc)
        if pages is not None:
            page_indices = [p for p in pages if 0 <= p < pc]
        elif page_ranges:
            page_indices = _expand_ranges(page_ranges, pc)
            if not page_indices:
                page_indices = list(range(pc))
        else:
            page_indices = list(range(pc))

        if not page_indices:
            logger.warning("No pages to print for %s", pdf_path)
            return

        _configure_printer_for_a4_portrait(printer, dpi=dpi, duplex=duplex)
        painter = QPainter()
        if not painter.begin(printer):
            logger.error("QPainter.begin(printer) failed")
            return

        try:
            for i, page_num in enumerate(page_indices):
                if i > 0:
                    printer.newPage()
                page = doc[page_num]
                pix = page.get_pixmap(dpi=int(dpi), alpha=False)
                img = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format.Format_RGB888,
                )
                painter.drawImage(QPointF(0.0, 0.0), img)
        finally:
            painter.end()
    finally:
        doc.close()
