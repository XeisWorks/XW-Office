"""PDF print dialog for Rechnungen module."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import fitz
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import QStyledItemDelegate
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
    QPushButton,
    QTableView,
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


class _PrintPlanModel(QAbstractTableModel):
    _headers = ["Seitenbereich", "Druckprofil"]

    def __init__(self, profiles: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profiles = profiles
        self._rows: list[dict[str, str]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else 2

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return row.get("range", "Alle Seiten")
            profile_id = row.get("profile_id", "")
            return self._label_for_profile(profile_id)
        if role == Qt.ItemDataRole.EditRole:
            return row.get("range", "Alle Seiten") if index.column() == 0 else row.get("profile_id", "")
        return None

    def setData(self, index: QModelIndex, value: object, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return False
        if index.column() == 0:
            self._rows[index.row()]["range"] = str(value or "").strip() or "Alle Seiten"
        else:
            self._rows[index.row()]["profile_id"] = str(value or "").strip()
        self.dataChanged.emit(index, index, [role, Qt.ItemDataRole.DisplayRole])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._headers[section]
        return None

    def add_row(self, range_text: str, profile_id: str) -> None:
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append({"range": str(range_text or "Alle Seiten").strip() or "Alle Seiten", "profile_id": str(profile_id or "").strip()})
        self.endInsertRows()

    def remove_row(self, row: int) -> None:
        if not (0 <= row < len(self._rows)):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._rows[row]
        self.endRemoveRows()

    def plan(self) -> list[dict[str, str]]:
        return [dict(row) for row in self._rows]

    def _label_for_profile(self, profile_id: str) -> str:
        for candidate_id, label in self._profiles:
            if candidate_id == profile_id:
                return label
        return ""


class _PrintProfileDelegate(QStyledItemDelegate):
    def __init__(self, profiles: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profiles = profiles

    def createEditor(self, parent: QWidget, _option, _index: QModelIndex) -> QComboBox:  # type: ignore[override]
        combo = QComboBox(parent)
        for candidate_id, label in self._profiles:
            combo.addItem(label, candidate_id)
        return combo

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        if isinstance(editor, QComboBox):
            current = str(index.data(Qt.ItemDataRole.EditRole) or "")
            found = editor.findData(current)
            editor.setCurrentIndex(max(0, found))

    def setModelData(self, editor: QWidget, model: QAbstractTableModel, index: QModelIndex) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, str(editor.currentData() or ""))


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
        root.addLayout(form)

        self._profiles = [
            (profile.id, f"{profile.id} - {profile.label or profile.printer_name}".strip())
            for profile in container.config.printing.all_profiles()
            if profile.id
        ]
        root.addWidget(QLabel("Druckplan:"))
        self._plan_model = _PrintPlanModel(self._profiles, self)
        self._plan_table = QTableView(self)
        self._plan_table.setModel(self._plan_model)
        self._plan_table.setItemDelegateForColumn(1, _PrintProfileDelegate(self._profiles, self._plan_table))
        self._plan_table.horizontalHeader().setStretchLastSection(True)
        self._plan_table.setMinimumHeight(130)
        root.addWidget(self._plan_table)
        plan_buttons = QHBoxLayout()
        add_row_btn = QPushButton("Zeile hinzufuegen")
        add_row_btn.clicked.connect(lambda: self._add_plan_row("Alle Seiten", ""))
        plan_buttons.addWidget(add_row_btn)
        remove_row_btn = QPushButton("Zeile entfernen")
        remove_row_btn.clicked.connect(self._remove_selected_plan_row)
        plan_buttons.addWidget(remove_row_btn)
        plan_buttons.addStretch()
        root.addLayout(plan_buttons)
        self._load_initial_plan_rows()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.resize(620, 360)

    def values(self) -> tuple[str, str, list[dict[str, str]]]:
        path = self._path_edit.text().strip()
        plan = self._parse_plan()
        profile_id = str(plan[0].get("profile_id") or "").strip() if plan else ""
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

    def _load_initial_plan_rows(self) -> None:
        if self._piece.print_plan:
            for entry in self._piece.print_plan:
                if not isinstance(entry, dict):
                    continue
                self._add_plan_row(
                    str(entry.get("range") or "Alle Seiten").strip() or "Alle Seiten",
                    str(entry.get("profile_id") or "").strip(),
                )
        else:
            self._add_plan_row("Alle Seiten", str(self._piece.print_profile_id or "").strip())

    def _add_plan_row(self, range_text: str, profile_id: str) -> None:
        self._plan_model.add_row(range_text, profile_id)

    def _remove_selected_plan_row(self) -> None:
        self._plan_model.remove_row(self._plan_table.currentIndex().row())

    def _parse_plan(self) -> list[dict[str, str]]:
        plan: list[dict[str, str]] = []
        for row in self._plan_model.plan():
            range_text = str(row.get("range") or "").strip() or "Alle Seiten"
            profile_id = str(row.get("profile_id") or "").strip()
            if not profile_id:
                raise RuntimeError("Jede Druckplan-Zeile braucht ein Druckprofil.")
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
