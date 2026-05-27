"""Render PDF pages through PyMuPDF and QPrinter without external viewers."""
from __future__ import annotations

import logging

import fitz  # PyMuPDF
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
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
    """Map Qt print dialog page range to 0-based indices."""
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


def _draw_origin(printer: QPrinter, image: QImage, *, center_on_page: bool) -> QPointF:
    if not center_on_page:
        return QPointF(0.0, 0.0)
    rect = printer.pageRect(QPrinter.Unit.DevicePixel)
    if not rect.isValid() or rect.width() <= 0 or rect.height() <= 0:
        return QPointF(0.0, 0.0)
    return QPointF(
        rect.x() + (rect.width() - image.width()) / 2.0,
        rect.y() + (rect.height() - image.height()) / 2.0,
    )


def print_pdf_with_qprinter(
    pdf_path: str,
    printer_name: str,
    *,
    pages: list[int] | None = None,
    copies: int = 1,
    dpi: int | None = None,
    center_on_page: bool = True,
) -> None:
    """Print a PDF with PyMuPDF + QPrinter/QPainter.

    The selected Windows printer queue is authoritative for paper size, duplex,
    tray, color, orientation, quality, and vendor-specific settings. This
    function only selects the queue, optionally sets render resolution, renders
    pages to bitmaps, and draws them without resizing.
    """
    render_dpi = max(int(dpi or INVOICE_DPI), 1)
    effective_copies = max(int(copies or 1), 1)
    doc = fitz.open(pdf_path)
    try:
        page_count = len(doc)
        page_indices = list(range(page_count)) if pages is None else [p for p in pages if 0 <= p < page_count]
        if not page_indices:
            logger.warning("No pages to print for %s", pdf_path)
            return

        for copy_index in range(effective_copies):
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
            printer.setPrinterName(printer_name)
            if dpi is not None:
                printer.setResolution(render_dpi)

            painter = QPainter()
            if not painter.begin(printer):
                logger.error("QPainter.begin(printer) failed for %s", printer_name)
                return
            try:
                for page_offset, page_num in enumerate(page_indices):
                    if page_offset > 0:
                        printer.newPage()
                    page = doc[page_num]
                    pix = page.get_pixmap(dpi=render_dpi, alpha=False)
                    image = QImage(
                        pix.samples,
                        pix.width,
                        pix.height,
                        pix.stride,
                        QImage.Format.Format_RGB888,
                    )
                    painter.drawImage(_draw_origin(printer, image, center_on_page=center_on_page), image)
            finally:
                painter.end()
            logger.info(
                "PDF print copy dispatched: printer='%s' file='%s' copy=%s/%s dpi=%s pages=%s",
                printer_name,
                pdf_path,
                copy_index + 1,
                effective_copies,
                render_dpi,
                page_indices,
            )
    finally:
        doc.close()


# Backward-compatible name used by older UI helpers.
def print_pdf(
    pdf_path: str,
    printer: QPrinter,
    dpi: int = MUSIC_DPI,
    *,
    pages: list[int] | None = None,
    page_ranges: list[range] | None = None,
    center_on_page: bool = True,
) -> None:
    page_indices = pages
    if page_indices is None and page_ranges:
        doc = fitz.open(pdf_path)
        try:
            page_indices = _expand_ranges(page_ranges, len(doc)) or None
        finally:
            doc.close()
    printer_name = str(printer.printerName() or "").strip()
    if not printer_name:
        raise RuntimeError("Kein Drucker ausgewaehlt")
    print_pdf_with_qprinter(
        pdf_path,
        printer_name,
        pages=page_indices,
        copies=1,
        dpi=dpi,
        center_on_page=center_on_page,
    )
