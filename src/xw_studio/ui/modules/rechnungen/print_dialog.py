"""PDF print dialog for Rechnungen module."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import fitz
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.printer_detect import discover_printers, evaluate_printer_status
from xw_studio.core.types import PrinterStatus
from xw_studio.services.inventory import InventoryService
from xw_studio.services.products.catalog import Product, ProductCatalogService
from xw_studio.services.products.print_decision import PieceBlock
from xw_studio.services.printing.print_jobs import PdfPrintJob, PrintJobKind
from xw_studio.services.printing.print_queue import PrintQueueService
from xw_studio.services.printing.planned_pdf_printer import print_pdf_by_plan
from xw_studio.services.printing.pdf_renderer import page_indices_from_qprinter

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


class ProductPrintConfigDialog(QDialog):
    def __init__(self, parent: QWidget | None, container: Container, piece: PieceBlock) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Druck konfigurieren - {piece.sku}")
        self._container = container
        self._piece = piece

        root = QVBoxLayout(self)
        root.setSpacing(10)

        heading = QLabel(f"{piece.sku} - {piece.name}")
        heading.setWordWrap(True)
        root.addWidget(heading)

        form = QFormLayout()
        self._path_edit = QLineEdit(str(piece.print_file_path or ""))
        browse_row = QHBoxLayout()
        browse_row.addWidget(self._path_edit, stretch=1)
        browse_btn = QPushButton("PDF waehlen")
        browse_btn.clicked.connect(self._browse_pdf)
        browse_row.addWidget(browse_btn)
        form.addRow("Druckpfad:", browse_row)

        self._profile_combo = QComboBox()
        profiles = container.config.printing.all_profiles()
        current_profile = str(piece.print_profile_id or "").strip()
        for profile in profiles:
            if not profile.id:
                continue
            label = f"{profile.id} - {profile.label or profile.printer_name}".strip()
            self._profile_combo.addItem(label, profile.id)
        if current_profile:
            index = self._profile_combo.findData(current_profile)
            if index >= 0:
                self._profile_combo.setCurrentIndex(index)
        self._profile_combo.currentIndexChanged.connect(self._sync_plan_profile)
        form.addRow("Profil:", self._profile_combo)
        root.addLayout(form)

        self._plan_edit = QPlainTextEdit()
        self._plan_edit.setMinimumHeight(110)
        self._plan_edit.setPlainText(self._initial_plan_text())
        root.addWidget(QLabel("Druckplan JSON:"))
        root.addWidget(self._plan_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.resize(620, 360)

    def values(self) -> tuple[str, str, list[dict[str, str]]]:
        path = self._path_edit.text().strip()
        profile_id = str(self._profile_combo.currentData() or "").strip()
        plan = self._parse_plan()
        return path, profile_id, plan

    def accept(self) -> None:
        try:
            path, profile_id, plan = self.values()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Druck konfigurieren", str(exc))
            return
        if not path:
            QMessageBox.warning(self, "Druck konfigurieren", "Bitte einen PDF-Druckpfad waehlen.")
            return
        if not profile_id and not plan:
            QMessageBox.warning(self, "Druck konfigurieren", "Bitte Profil oder Druckplan angeben.")
            return
        super().accept()

    def _browse_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Produkt-PDF waehlen", self._path_edit.text(), "PDF (*.pdf)")
        if path:
            self._path_edit.setText(path)

    def _initial_plan_text(self) -> str:
        import json

        if self._piece.print_plan:
            return json.dumps(self._piece.print_plan, ensure_ascii=False, indent=2)
        profile_id = str(self._piece.print_profile_id or "").strip() or self._current_profile_id()
        if profile_id:
            return json.dumps([{"range": "Alle Seiten", "profile_id": profile_id}], ensure_ascii=False, indent=2)
        return "[]"

    def _current_profile_id(self) -> str:
        return str(self._profile_combo.currentData() or "").strip()

    def _sync_plan_profile(self) -> None:
        if self._plan_edit.toPlainText().strip() not in {"", "[]"}:
            return
        profile_id = self._current_profile_id()
        if profile_id:
            self._plan_edit.setPlainText(f'[{{"range": "Alle Seiten", "profile_id": "{profile_id}"}}]')

    def _parse_plan(self) -> list[dict[str, str]]:
        import json

        raw = self._plan_edit.toPlainText().strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Druckplan ist kein gueltiges JSON: {exc}") from exc
        if not isinstance(data, list):
            raise RuntimeError("Druckplan muss eine JSON-Liste sein.")
        plan: list[dict[str, str]] = []
        for entry in data:
            if not isinstance(entry, dict):
                raise RuntimeError("Jeder Druckplan-Eintrag muss ein Objekt sein.")
            range_text = str(entry.get("range") or "Alle Seiten").strip() or "Alle Seiten"
            profile_id = str(entry.get("profile_id") or "").strip()
            if not profile_id:
                raise RuntimeError("Jeder Druckplan-Eintrag braucht profile_id.")
            plan.append({"range": range_text, "profile_id": profile_id})
        return plan


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


def _configure_missing_piece_print(parent: QWidget, container: Container, piece: PieceBlock) -> bool:
    dialog = ProductPrintConfigDialog(parent, container, piece)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    path, profile_id, plan = dialog.values()

    inv: InventoryService = container.resolve(InventoryService)
    inv.save_product_print_config(
        sku=piece.sku,
        name=piece.name,
        print_file_path=path,
        print_profile_id=profile_id,
        print_plan=plan,
    )

    if piece.product is None:
        piece.product = Product(id=f"settings::{piece.sku}", sku=piece.sku, name=piece.name, print_file_path=path)
    else:
        piece.product.print_file_path = path
    piece.print_profile_id = profile_id
    piece.print_plan = plan

    try:
        container.resolve(ProductCatalogService).reload_from_settings()
    except Exception as exc:
        logger.debug("Product catalog reload after print config save failed: %s", exc)
    return True


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

    if not piece.has_direct_print_config and not _configure_missing_piece_print(parent, container, piece):
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
