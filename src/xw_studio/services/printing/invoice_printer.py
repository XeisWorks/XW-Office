"""Legacy-compatible invoice printer using the blueprint Qt/PyMuPDF backend."""
from __future__ import annotations

import logging
import os
import tempfile

from xw_studio.core.config import PrintingSection
from xw_studio.services.printing.print_jobs import PdfPrintJob
from xw_studio.services.printing.print_queue import PrintQueueService, global_print_queue

logger = logging.getLogger(__name__)


def _looks_like_pdf(content: bytes) -> bool:
    if not content:
        return False
    return b"%PDF-" in bytes(content[:1024])


class InvoicePrinter:
    """Drop-in equivalent to old app's InvoicePrinter with new print engine."""

    def __init__(self, printing: PrintingSection, print_queue: PrintQueueService | None = None) -> None:
        self._printing = printing
        self._print_queue = print_queue

    def _printer_name(self) -> str:
        profile = self._printing.resolve_profile("invoice")
        if profile is not None and profile.printer_name.strip():
            return profile.printer_name.strip()
        explicit = str(self._printing.invoice_printer or "").strip()
        if explicit:
            return explicit
        names = [str(name).strip() for name in self._printing.configured_printer_names if str(name).strip()]
        return names[0] if names else ""

    def print_pdf_bytes(self, pdf_bytes: bytes) -> None:
        printer_name = self._printer_name()
        if not printer_name:
            raise RuntimeError("Kein Rechnungsdrucker konfiguriert")
        if not _looks_like_pdf(pdf_bytes):
            raise RuntimeError("Rechnungs-PDF ungueltig (kein PDF-Header gefunden)")

        temp_path = ""
        scheduled = False
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as handle:
                handle.write(pdf_bytes)
                temp_path = handle.name
            self._queue_file(temp_path, printer_name)
            scheduled = True
        finally:
            if temp_path and not scheduled:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _queue_file(self, pdf_path: str, printer_name: str) -> None:
        try:
            size = os.path.getsize(pdf_path)
        except OSError:
            size = -1
        logger.info(
            "Invoice print dispatch: printer='%s' file='%s' size=%s",
            printer_name,
            pdf_path,
            size,
        )
        profile = self._printing.resolve_profile("invoice")
        dpi = int(profile.dpi) if profile is not None and profile.dpi else None
        queue = self._print_queue or global_print_queue()
        queue.enqueue(
            PdfPrintJob(
                pdf_path=pdf_path,
                printer_name=printer_name,
                copies=1,
                dpi=dpi,
                job_kind="invoice",
                description="Rechnungsdruck",
                cleanup_paths=(pdf_path,),
            )
        )
