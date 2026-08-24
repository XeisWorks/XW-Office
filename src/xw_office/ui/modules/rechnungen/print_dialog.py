"""PDF print dialog for Rechnungen module."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import fitz
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QUrl
from PySide6.QtGui import QDesktopServices
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
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.printer_detect import discover_printers, evaluate_printer_status
from xw_office.core.signals import AppSignals
from xw_office.core.types import PrinterStatus
from xw_office.services.background_jobs import BackgroundJobManager
from xw_office.services.inventory import InventoryService
from xw_office.services.products.catalog import Product, ProductCatalogService
from xw_office.services.products.print_decision import PieceBlock
from xw_office.services.printing.print_jobs import PdfPrintJob, PrintJobKind
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.printing.planned_pdf_printer import page_indices_from_range_text, print_pdf_by_plan
from xw_office.services.printing.pdf_renderer import page_indices_from_qprinter

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)

_PRODUCT_PRINT_PROFILE_IDS = {"noten_simplex", "noten_duplex", "noten_a5", "brochure_mono", "brochure_duo"}


def _format_page_ranges(pages: list[int]) -> str:
    """Compress a sorted list of 1-based page numbers into "1-3, 5, 7-9" form."""
    if not pages:
        return ""
    ranges: list[str] = []
    start = prev = pages[0]
    for page in pages[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = page
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


class _PrintPlanModel(QAbstractTableModel):
    _headers = ["Seitenbereich", "Drucker"]

    def __init__(self, profiles: list[tuple[str, str, str, str]], parent: QWidget | None = None) -> None:
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
            return self._printer_for_profile(profile_id)
        if role == Qt.ItemDataRole.EditRole:
            return row.get("range", "Alle Seiten") if index.column() == 0 else row.get("profile_id", "")
        return None

    def setData(self, index: QModelIndex, value: object, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return False
        if index.column() == 0:
            self._rows[index.row()]["range"] = str(value or "").strip() or "Alle Seiten"
        elif index.column() == 1:
            self._rows[index.row()]["profile_id"] = str(value or "").strip()
        else:
            return False
        self.dataChanged.emit(index, index, [role, Qt.ItemDataRole.DisplayRole])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() in {0, 1}:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

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

    def _printer_for_profile(self, profile_id: str) -> str:
        for candidate_id, _label, printer, _backend in self._profiles:
            if candidate_id == profile_id:
                return printer
        return ""


class _PrintProfileDelegate(QStyledItemDelegate):
    def __init__(self, profiles: list[tuple[str, str, str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profiles = profiles

    def createEditor(self, parent: QWidget, _option, _index: QModelIndex) -> QComboBox:  # type: ignore[override]
        combo = QComboBox(parent)
        for candidate_id, label, printer, _backend in self._profiles:
            display = printer or label or candidate_id
            combo.addItem(display, candidate_id)
        return combo

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        if isinstance(editor, QComboBox):
            current = str(index.data(Qt.ItemDataRole.EditRole) or "")
            found = editor.findData(current)
            editor.setCurrentIndex(max(0, found))
            if not bool(editor.property("xw_print_plan_commit_connected")):
                editor.currentIndexChanged.connect(
                    lambda _selected, combo=editor: self.commitData.emit(combo)
                )
                editor.setProperty("xw_print_plan_commit_connected", True)

    def setModelData(self, editor: QWidget, model: QAbstractTableModel, index: QModelIndex) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, str(editor.currentData() or ""))


class ProductPrintConfigDialog(QDialog):
    def __init__(self, parent: QWidget | None, container: Container, piece: PieceBlock) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Druck konfigurieren - {piece.sku}")
        self._container = container
        self._piece = piece
        self._page_count: int | None = None

        root = QVBoxLayout(self)
        root.setSpacing(10)

        heading = QLabel(f"{piece.sku} - {piece.name}")
        heading.setWordWrap(True)
        root.addWidget(heading)

        form = QFormLayout()
        self._path_edit = QLineEdit(str(piece.print_file_path or ""))
        self._path_edit.textChanged.connect(self._refresh_pdf_status)
        browse_row = QHBoxLayout()
        browse_row.addWidget(self._path_edit, stretch=1)
        browse_btn = QPushButton("PDF waehlen")
        browse_btn.clicked.connect(self._browse_pdf)
        browse_row.addWidget(browse_btn)
        open_pdf_btn = QPushButton("PDF oeffnen")
        open_pdf_btn.clicked.connect(self._open_pdf)
        browse_row.addWidget(open_pdf_btn)
        open_folder_btn = QPushButton("Ordner")
        open_folder_btn.clicked.connect(self._open_pdf_folder)
        browse_row.addWidget(open_folder_btn)
        form.addRow("Druckpfad:", browse_row)
        self._pdf_status = QLabel("")
        self._pdf_status.setWordWrap(True)
        form.addRow("PDF-Status:", self._pdf_status)
        root.addLayout(form)

        self._profiles = [
            (
                profile.id,
                profile.label or profile.printer_name or profile.id,
                profile.printer_name or "-",
                self._backend_label(profile.backend),
            )
            for profile in container.config.printing.all_profiles()
            if profile.id in _PRODUCT_PRINT_PROFILE_IDS
        ]
        root.addWidget(QLabel("Druckplan:"))
        self._plan_model = _PrintPlanModel(self._profiles, self)
        self._plan_table = QTableView(self)
        self._plan_table.setModel(self._plan_model)
        self._plan_table.setItemDelegateForColumn(1, _PrintProfileDelegate(self._profiles, self._plan_table))
        self._plan_model.dataChanged.connect(lambda *_args: self._refresh_plan_summary())
        self._plan_model.rowsInserted.connect(lambda *_args: self._refresh_plan_summary())
        self._plan_model.rowsRemoved.connect(lambda *_args: self._refresh_plan_summary())
        self._plan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._plan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
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
        self._plan_summary = QLabel("")
        self._plan_summary.setWordWrap(True)
        root.addWidget(self._plan_summary)
        self._title_override_note = QLabel("")
        self._title_override_note.setWordWrap(True)
        self._title_override_note.setStyleSheet("color: #f59e0b;")
        self._title_override_note.hide()
        root.addWidget(self._title_override_note)
        self._refresh_pdf_status()
        self._refresh_plan_summary()
        self._refresh_title_override_note()

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
            QMessageBox.warning(self, "Druck konfigurieren", "Bitte Drucker oder Druckplan angeben.")
            return
        pdf_path = self._pdf_path()
        if not pdf_path.is_file():
            QMessageBox.warning(self, "Druck konfigurieren", "Die gewaehlte PDF-Datei existiert nicht.")
            return
        if self._page_count is None:
            self._refresh_pdf_status()
        if self._page_count is None:
            QMessageBox.warning(self, "Druck konfigurieren", "Die PDF-Datei konnte nicht geoeffnet werden.")
            return
        super().accept()

    def _browse_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Produkt-PDF waehlen", self._path_edit.text(), "PDF (*.pdf)")
        if path:
            self._path_edit.setText(path)

    def _open_pdf(self) -> None:
        if not self._path_edit.text().strip():
            return
        path = self._pdf_path()
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_pdf_folder(self) -> None:
        if not self._path_edit.text().strip():
            return
        path = self._pdf_path()
        target = path.parent if path.parent.exists() else None
        if target is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

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
                raise RuntimeError("Jede Druckplan-Zeile braucht einen Drucker.")
            plan.append({"range": range_text, "profile_id": profile_id})
        return plan

    def _pdf_path(self) -> Path:
        return Path(self._path_edit.text().strip())

    def _refresh_pdf_status(self) -> None:
        raw_path = self._path_edit.text().strip()
        self._page_count = None
        if not raw_path:
            self._pdf_status.setText("Kein PDF-Pfad gewaehlt.")
            self._refresh_plan_summary()
            return
        path = Path(raw_path)
        if not path.is_file():
            self._pdf_status.setText(f"Datei fehlt: {path}")
            self._refresh_plan_summary()
            return
        doc = None
        try:
            doc = fitz.open(str(path))
            self._page_count = len(doc)
        except Exception as exc:  # noqa: BLE001 - shown to user as validation status.
            self._pdf_status.setText(f"PDF kann nicht gelesen werden: {exc}")
            self._refresh_plan_summary()
            return
        finally:
            try:
                if doc is not None:
                    doc.close()
            except Exception:
                pass
        self._pdf_status.setText(f"PDF gefunden: {path.name} ({self._page_count} Seite(n))")
        self._refresh_plan_summary()

    def _refresh_plan_summary(self) -> None:
        if not hasattr(self, "_plan_summary"):
            return
        lines: list[str] = []
        for row in self._plan_model.plan():
            profile_id = str(row.get("profile_id") or "").strip()
            range_text = str(row.get("range") or "").strip() or "Alle Seiten"
            printer = self._profile_printer(profile_id)
            lines.append(f"{range_text} -> {printer}")
        suffix = f" | PDF: {self._page_count} Seite(n)" if self._page_count is not None else ""
        summary = "Druckplan: " + ("; ".join(lines) if lines else "kein Plan") + suffix
        coverage_note = self._plan_coverage_note()
        if coverage_note:
            summary += "\n" + coverage_note
        self._plan_summary.setText(summary)

    def _plan_coverage_note(self) -> str:
        """Report gaps/overlaps across plan rows so a copy-paste typo in a
        page range shows up here instead of on paper."""
        if self._page_count is None:
            return ""
        rows = self._plan_model.plan()
        if not rows:
            return ""
        total_pages = self._page_count
        covered = [0] * total_pages
        for row in rows:
            range_text = str(row.get("range") or "").strip() or "Alle Seiten"
            try:
                indices = page_indices_from_range_text(range_text, page_count=total_pages)
            except RuntimeError as exc:
                return f"⚠ {exc}"
            target_indices = range(total_pages) if indices is None else indices
            for index in target_indices:
                covered[index] += 1
        missing = [index + 1 for index, count in enumerate(covered) if count == 0]
        overlapping = [index + 1 for index, count in enumerate(covered) if count > 1]
        if not missing and not overlapping:
            return f"✓ Deckt alle {total_pages} Seite(n) genau einmal ab."
        parts: list[str] = []
        if missing:
            parts.append(f"Luecke bei Seite(n) {_format_page_ranges(missing)}")
        if overlapping:
            parts.append(f"Ueberlappung bei Seite(n) {_format_page_ranges(overlapping)}")
        return "⚠ " + "; ".join(parts)

    def _refresh_title_override_note(self) -> None:
        if not hasattr(self, "_title_override_note"):
            return
        try:
            catalog: ProductCatalogService = self._container.resolve(ProductCatalogService)
            override_titles = catalog.title_overrides_for_sku(self._piece.sku)
        except Exception as exc:  # noqa: BLE001 - purely informational note.
            logger.debug("Title override lookup failed for %s: %s", self._piece.sku, exc)
            return
        current_title = str(self._piece.name or "").strip()
        other_titles = [title for title in override_titles if title != current_title]
        if not other_titles:
            self._title_override_note.hide()
            return
        shown = other_titles[:5]
        joined = ", ".join(f'"{title}"' for title in shown)
        if len(other_titles) > len(shown):
            joined += f" (+{len(other_titles) - len(shown)} weitere)"
        self._title_override_note.setText(
            "⚠ Fuer diese SKU gibt es zusaetzlich titelspezifische Druckplaene, die weiterhin diesen "
            f"Standard ueberschreiben und hier NICHT bearbeitet werden: {joined}."
        )
        self._title_override_note.show()

    def _profile_printer(self, profile_id: str) -> str:
        for candidate_id, _label, printer, _backend in self._profiles:
            if candidate_id == profile_id:
                return printer
        return "-"

    @staticmethod
    def _backend_label(raw_backend: str) -> str:
        backend = str(raw_backend or "qt_raster").strip().lower()
        if backend == "pdf_xchange":
            return "BACKEND: PDF-XCHANGE NATIV"
        return "BACKEND: Qt Raster"


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

    if piece.product is None:
        piece.product = Product(id=f"settings::{piece.sku}", sku=piece.sku, name=piece.name, print_file_path=path)
    else:
        piece.product.print_file_path = path
    piece.print_profile_id = profile_id
    piece.print_plan = plan

    inv: InventoryService = container.resolve(InventoryService)
    try:
        signals: AppSignals | None = container.resolve(AppSignals)
    except KeyError:
        signals = None

    def persist(_token: object) -> str:
        inv.save_product_print_config(
            sku=piece.sku,
            name=piece.name,
            print_file_path=path,
            print_profile_id=profile_id,
            print_plan=plan,
        )
        container.resolve(ProductCatalogService).reload_from_settings()
        return piece.sku

    def saved(_payload: object) -> None:
        if signals is not None:
            signals.inventory_changed.emit()
            signals.status_message.emit(f"Druckkonfiguration gespeichert: {piece.sku}", 5000)

    def failed(exc: Exception) -> None:
        logger.error("Product print config save failed for %s: %s", piece.sku, exc)
        if signals is not None:
            signals.task_error.emit("Druckkonfiguration", str(exc))
            signals.status_message.emit(f"Druckkonfiguration konnte nicht gespeichert werden: {piece.sku}", 12000)

    try:
        background_jobs = container.resolve(BackgroundJobManager)
    except KeyError:
        persist(object())
        saved(piece.sku)
    else:
        background_jobs.submit_callable(
            queue="database",
            priority=20,
            key=f"save-product-print-config:{piece.sku}",
            fn=persist,
            on_result=saved,
            on_error=failed,
            owner=parent,
            replace="allow_parallel",
        )
    return True


def prepare_piece_pdf_print(
    parent: QWidget,
    container: Container,
    *,
    piece: PieceBlock,
    copies: int = 1,
    wait: bool = False,
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
        kwargs = {
            "print_plan": piece.print_plan,
            "profile_id": piece.print_profile_id,
            "copies": effective_copies,
            "page_count": page_count,
            "print_queue": queue,
            "job_kind": "product",
        }
        if wait:
            kwargs["wait"] = True
        print_pdf_by_plan(path, container.config.printing, **kwargs)

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
