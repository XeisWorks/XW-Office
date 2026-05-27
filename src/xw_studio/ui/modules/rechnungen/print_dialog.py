"""PDF print dialog for Rechnungen module."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import fitz
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from xw_studio.core.printer_detect import discover_printers, evaluate_printer_status
from xw_studio.core.types import PrinterStatus
from xw_studio.services.products.print_decision import PieceBlock
from xw_studio.services.printing.print_jobs import PdfPrintJob, PrintJobKind
from xw_studio.services.printing.print_queue import PrintQueueService
from xw_studio.services.printing.planned_pdf_printer import print_pdf_by_plan
from xw_studio.services.printing.pdf_renderer import page_indices_from_qprinter

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


def _check_printer_runtime(parent: QWidget, container: Container, printer: QPrinter | None = None) -> bool:
    configured = list(container.config.printing.configured_printer_names)
    discovered = discover_printers()
    status = evaluate_printer_status(discovered, configured)
    if status == PrinterStatus.RED:
        QMessageBox.warning(
            parent,
            "Druck nicht verfuegbar",
            "Kein konfigurierter Drucker ist verfuegbar (Ampel rot).",
        )
        return False

    if printer is not None and configured:
        name = (printer.printerName() or "").strip()
        if name and name not in configured:
            QMessageBox.warning(
                parent,
                "Falscher Drucker",
                "Der gewaehlt Drucker ist nicht in den konfigurierten Druckern enthalten.",
            )
            return False
    return True


def _print_with_dialog(
    parent: QWidget,
    container: Container,
    *,
    title: str,
    job_kind: PrintJobKind,
) -> None:
    if not _check_printer_runtime(parent, container):
        return

    path, _ = QFileDialog.getOpenFileName(
        parent,
        title,
        "",
        "PDF (*.pdf);;Alle Dateien (*.*)",
    )
    if not path:
        return

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    default_name = QPrinterInfo.defaultPrinter().printerName()
    if default_name:
        printer.setPrinterName(default_name)
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return

    if not _check_printer_runtime(parent, container, printer):
        return

    doc = fitz.open(path)
    try:
        page_count = len(doc)
    finally:
        doc.close()

    indices = page_indices_from_qprinter(printer, page_count)
    printer_name = str(printer.printerName() or "").strip()
    if not printer_name:
        QMessageBox.warning(parent, "Druck", "Kein Drucker ausgewaehlt.")
        return

    queue: PrintQueueService = container.resolve(PrintQueueService)
    queue.enqueue(
        PdfPrintJob(
            pdf_path=path,
            printer_name=printer_name,
            pages=indices,
            copies=1,
            dpi=None,
            job_kind=job_kind,
            description=f"Manueller PDF-Druck: {path}",
        )
    )


def run_invoice_pdf_print(parent: QWidget, container: Container) -> None:
    """Pick a PDF, show print dialog, and queue it with the selected printer."""
    _print_with_dialog(
        parent,
        container,
        title="PDF auswählen (Rechnung)",
        job_kind="invoice",
    )


def run_label_pdf_print(parent: QWidget, container: Container) -> None:
    """Pick a label PDF, show print dialog, and queue it with the selected printer."""
    _print_with_dialog(
        parent,
        container,
        title="PDF auswählen (Label)",
        job_kind="label",
    )


def run_plc_label_pdf_print(
    parent: QWidget,
    container: Container,
    *,
    invoice_number: str,
) -> None:
    """Pick and print PLC label PDF for a specific invoice row."""
    title = f"PLC-Label PDF auswählen ({invoice_number})" if invoice_number else "PLC-Label PDF auswählen"
    _print_with_dialog(
        parent,
        container,
        title=title,
        job_kind="label",
    )


def run_music_pdf_print(parent: QWidget, container: Container) -> None:
    """Pick a music PDF, show print dialog, and queue it with the selected printer."""
    _print_with_dialog(
        parent,
        container,
        title="PDF auswählen (Noten)",
        job_kind="music",
    )


def prepare_piece_pdf_print(
    parent: QWidget,
    container: Container,
    *,
    piece: PieceBlock,
    copies: int = 1,
) -> Callable[[], None] | None:
    """Validate one product print and return the blocking print job."""
    if not _check_printer_runtime(parent, container):
        return None

    path_obj = piece.print_file_path
    if path_obj is None:
        QMessageBox.warning(
            parent,
            "Produktdruck",
            f"Kein PDF-Pfad für SKU {piece.sku} konfiguriert.",
        )
        return None
    path = str(path_obj)
    doc = None
    try:
        doc = fitz.open(path)
        page_count = len(doc)
    except Exception as exc:
        QMessageBox.critical(
            parent,
            "Produktdruck fehlgeschlagen",
            f"Die Produkt-PDF konnte nicht geoeffnet werden:\n\n{exc}",
        )
        return None
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception:
            pass

    if not piece.has_direct_print_config:
        QMessageBox.warning(
            parent,
            "Produktdruck",
            f"Fuer SKU {piece.sku} fehlt im neuen Repo ein vollstaendiger Druckpfad.\n\n"
            "Bitte im Produkte-Modul PDF-Pfad und Druckplan/Profil pflegen.",
        )
        return None

    effective_copies = max(1, int(copies or piece.print_qty or piece.qty_needed or 1))

    def job() -> None:
        queue: PrintQueueService = container.resolve(PrintQueueService)
        print_pdf_by_plan(
            path,
            container.config.printing,
            print_plan=piece.print_plan,
            profile_id=piece.print_profile_id,
            copies=effective_copies,
            page_count=page_count,
            print_queue=queue,
            job_kind="product",
        )

    return job


def run_piece_pdf_print(
    parent: QWidget,
    container: Container,
    *,
    piece: PieceBlock,
    copies: int = 1,
) -> bool:
    """Print one product PDF from the product pipeline path.

    Returns ``True`` when printing was started successfully.
    """
    job = prepare_piece_pdf_print(parent, container, piece=piece, copies=copies)
    if job is None:
        return False
    try:
        job()
        return True
    except Exception as exc:
        logger.exception("Direct product print failed: %s", exc)
        QMessageBox.critical(
            parent,
            "Produktdruck fehlgeschlagen",
            f"Die Produkt-PDF konnte nicht ueber den hinterlegten Druckplan gedruckt werden:\n\n{exc}",
        )
        return False
