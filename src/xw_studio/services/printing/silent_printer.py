"""Silent printer routing for automated START workflows."""
from __future__ import annotations

import logging
from typing import Sequence

import fitz
from PySide6.QtCore import QRectF, Qt, QMarginsF
from PySide6.QtGui import QImage, QPainter, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from xw_studio.core.config import PrintingSection

logger = logging.getLogger(__name__)


def _preferred_printer_name(printing: PrintingSection, profile_id: str, fallback_index: int) -> str:
    profile = printing.resolve_profile(profile_id)
    if profile is not None and profile.printer_name.strip():
        return profile.printer_name.strip()
    names = [str(name).strip() for name in printing.configured_printer_names if str(name).strip()]
    if 0 <= fallback_index < len(names):
        return names[fallback_index]
    if names:
        return names[0]
    return ""


def _build_printer(*, preferred_name: str) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
    available = [p.printerName() for p in QPrinterInfo.availablePrinters()]
    if preferred_name and preferred_name in available:
        printer.setPrinterName(preferred_name)
        return printer
    default_name = QPrinterInfo.defaultPrinter().printerName().strip()
    if default_name:
        printer.setPrinterName(default_name)
    return printer


def _configure_invoice_layout(printer: QPrinter) -> None:
    layout = QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4),
        QPageLayout.Orientation.Portrait,
        QMarginsF(0.0, 0.0, 0.0, 0.0),
        QPageLayout.Unit.Millimeter,
    )
    printer.setPageLayout(layout)
    printer.setFullPage(True)


def _full_rect(printer: QPrinter) -> QRectF:
    layout = printer.pageLayout()
    rect = layout.fullRectPixels(printer.resolution())
    if rect.isValid() and rect.width() > 0 and rect.height() > 0:
        return QRectF(rect)
    fallback = printer.paperRect(QPrinter.Unit.DevicePixel)
    return QRectF(fallback)


def _aspect_fit_rect(container: QRectF, source_width: float, source_height: float) -> QRectF:
    if container.width() <= 0 or container.height() <= 0 or source_width <= 0 or source_height <= 0:
        return QRectF(container)
    scale = min(container.width() / float(source_width), container.height() / float(source_height))
    target_width = float(source_width) * scale
    target_height = float(source_height) * scale
    x = container.x() + (container.width() - target_width) / 2.0
    y = container.y() + (container.height() - target_height) / 2.0
    return QRectF(x, y, target_width, target_height)


def _actual_size_rect(container: QRectF, source_width: float, source_height: float) -> QRectF:
    if container.width() <= 0 or container.height() <= 0 or source_width <= 0 or source_height <= 0:
        return QRectF(container)
    if source_width <= container.width() and source_height <= container.height():
        x = container.x() + (container.width() - float(source_width)) / 2.0
        y = container.y() + (container.height() - float(source_height)) / 2.0
        return QRectF(x, y, float(source_width), float(source_height))
    return _aspect_fit_rect(container, source_width, source_height)


def _log_invoice_page_metrics(
    *,
    printer: QPrinter,
    page_index: int,
    page: fitz.Page,
    image: QImage,
    target_rect: QRectF,
) -> None:
    full_rect = _full_rect(printer)
    logger.info(
        "Invoice print layout: printer='%s' page=%s dpi=%s pdf_pt=(%.2f,%.2f) full_px=(%.2f,%.2f,%.2f,%.2f) target_px=(%.2f,%.2f,%.2f,%.2f) image_px=(%s,%s)",
        printer.printerName().strip(),
        page_index + 1,
        printer.resolution(),
        float(page.rect.width),
        float(page.rect.height),
        full_rect.x(),
        full_rect.y(),
        full_rect.width(),
        full_rect.height(),
        target_rect.x(),
        target_rect.y(),
        target_rect.width(),
        target_rect.height(),
        image.width(),
        image.height(),
    )


def print_pdf_bytes_silent(
    pdf_bytes: bytes,
    *,
    printing: PrintingSection,
    dpi: int,
    profile_id: str = "invoice",
    fallback_index: int = 0,
) -> str:
    """Print PDF bytes silently to configured printer and return printer name."""
    preferred_name = _preferred_printer_name(printing, profile_id, fallback_index)
    printer = _build_printer(preferred_name=preferred_name)
    selected_name = printer.printerName().strip()

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_count = len(doc)
        if page_count <= 0:
            raise RuntimeError("Leeres PDF")

        printer.setResolution(int(dpi))
        _configure_invoice_layout(printer)
        painter = QPainter()
        if not painter.begin(printer):
            raise RuntimeError("QPainter konnte Drucker nicht starten")
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        try:
            for page_num in range(page_count):
                if page_num > 0:
                    printer.newPage()
                page = doc[page_num]
                scale = float(dpi) / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                img = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format.Format_RGB888,
                )
                target_rect = _actual_size_rect(_full_rect(printer), img.width(), img.height())
                _log_invoice_page_metrics(
                    printer=printer,
                    page_index=page_num,
                    page=page,
                    image=img,
                    target_rect=target_rect,
                )
                painter.drawImage(target_rect, img)
        finally:
            painter.end()
    finally:
        doc.close()

    return selected_name or preferred_name or "(Defaultdrucker)"


def print_pdf_file_silent(
    pdf_path: str,
    *,
    printer_name: str,
    dpi: int,
) -> str:
    """Print a PDF file path silently to an explicit printer name."""
    with open(pdf_path, "rb") as handle:
        data = handle.read()
    printer = _build_printer(preferred_name=printer_name)
    selected_name = printer.printerName().strip()

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        page_count = len(doc)
        if page_count <= 0:
            raise RuntimeError("Leeres PDF")
        printer.setResolution(int(dpi))
        _configure_invoice_layout(printer)
        painter = QPainter()
        if not painter.begin(printer):
            raise RuntimeError("QPainter konnte Drucker nicht starten")
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        try:
            for page_num in range(page_count):
                if page_num > 0:
                    printer.newPage()
                page = doc[page_num]
                scale = float(dpi) / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                img = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format.Format_RGB888,
                )
                target_rect = _actual_size_rect(_full_rect(printer), img.width(), img.height())
                _log_invoice_page_metrics(
                    printer=printer,
                    page_index=page_num,
                    page=page,
                    image=img,
                    target_rect=target_rect,
                )
                painter.drawImage(target_rect, img)
        finally:
            painter.end()
    finally:
        doc.close()

    return selected_name or printer_name or "(Defaultdrucker)"


def print_text_label_silent(
    lines: Sequence[str],
    *,
    printing: PrintingSection,
    profile_id: str = "label",
    fallback_index: int = 1,
) -> str:
    """Print a simple address label text block silently and return printer name."""
    preferred_name = _preferred_printer_name(printing, profile_id, fallback_index)
    printer = _build_printer(preferred_name=preferred_name)
    selected_name = printer.printerName().strip()

    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("QPainter konnte Labeldruck nicht starten")
    try:
        rect = QRectF(painter.viewport())
        text = "\n".join(str(line).strip() for line in lines if str(line).strip())
        if not text:
            text = "(keine Labeldaten)"
        painter.drawText(rect.adjusted(40, 40, -40, -40), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), text)
    finally:
        painter.end()

    return selected_name or preferred_name or "(Defaultdrucker)"
