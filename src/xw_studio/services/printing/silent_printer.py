"""Backward-compatible internal printing helpers.

These helpers no longer call external PDF viewers. PDF paths are rendered by
PyMuPDF and printed through QPrinter/QPainter.
"""
from __future__ import annotations

import os
import tempfile
from typing import Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from xw_studio.core.config import PrintingSection
from xw_studio.services.printing.pdf_renderer import print_pdf_with_qprinter


def _preferred_printer_name(printing: PrintingSection, profile_id: str, fallback_index: int) -> str:
    profile = printing.resolve_profile(profile_id)
    if profile is not None and profile.printer_name.strip():
        return profile.printer_name.strip()
    names = [str(name).strip() for name in printing.configured_printer_names if str(name).strip()]
    if 0 <= fallback_index < len(names):
        return names[fallback_index]
    return names[0] if names else ""


def print_pdf_bytes_silent(
    pdf_bytes: bytes,
    *,
    printing: PrintingSection,
    dpi: int,
    profile_id: str = "invoice",
    fallback_index: int = 0,
) -> str:
    preferred_name = _preferred_printer_name(printing, profile_id, fallback_index)
    if not preferred_name:
        raise RuntimeError("Kein Drucker konfiguriert")
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as handle:
            handle.write(pdf_bytes)
            temp_path = handle.name
        print_pdf_with_qprinter(temp_path, preferred_name, dpi=dpi)
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
    return preferred_name


def print_pdf_file_silent(
    pdf_path: str,
    *,
    printer_name: str,
    dpi: int,
) -> str:
    print_pdf_with_qprinter(pdf_path, printer_name, dpi=dpi)
    return printer_name


def print_text_label_silent(
    lines: Sequence[str],
    *,
    printing: PrintingSection,
    profile_id: str = "label",
    fallback_index: int = 1,
) -> str:
    preferred_name = _preferred_printer_name(printing, profile_id, fallback_index)
    if not preferred_name:
        raise RuntimeError("Kein Labeldrucker konfiguriert")
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
    available = [p.printerName() for p in QPrinterInfo.availablePrinters()]
    if preferred_name in available:
        printer.setPrinterName(preferred_name)
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("QPainter konnte Labeldruck nicht starten")
    try:
        rect = QRectF(painter.viewport())
        text = "\n".join(str(line).strip() for line in lines if str(line).strip()) or "(keine Labeldaten)"
        painter.drawText(rect.adjusted(40, 40, -40, -40), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), text)
    finally:
        painter.end()
    return preferred_name
