"""Desktop workflow for a guided Product-Hub inventory count."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.product_hub.inventory_count import InventoryCountLineView, InventoryCountService, InventoryCountView

if TYPE_CHECKING:
    from xw_office.core.container import Container


class InventoryCountDialog(QDialog):
    """Start, record and confirm one immutable inventory count session."""

    HEADERS = ["SKU", "Titel", "System", "Gezahlt", "Differenz", "Notiz"]

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: InventoryCountService = container.resolve(InventoryCountService)
        self._view: InventoryCountView | None = None
        self._worker: BackgroundWorker | None = None
        self._line_edits: dict[str, QLineEdit] = {}
        self._note_edits: dict[str, QPlainTextEdit] = {}

        self.setWindowTitle("Gefuehrte Inventur")
        self.resize(980, 620)
        root = QVBoxLayout(self)
        self._status = QLabel("Inventurliste wird erstellt ...")
        self._status.setObjectName("productsStatusLabel")
        root.addWidget(self._status)
        self._table = QTableWidget(0, len(self.HEADERS), self)
        self._table.setHorizontalHeaderLabels(self.HEADERS)
        self._table.setSortingEnabled(False)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table, stretch=1)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        self._confirm_button = self._buttons.addButton(
            "Inventur bestaetigen", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._confirm_button.setEnabled(False)
        self._buttons.rejected.connect(self.reject)
        self._confirm_button.clicked.connect(self._confirm)
        root.addWidget(self._buttons)
        self._start()

    def _start(self) -> None:
        self._set_busy(True, "Inventurliste wird erstellt ...")
        self._worker = BackgroundWorker(self._service.start)
        self._worker.signals.result.connect(self._on_started)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()

    def _on_started(self, result: object) -> None:
        if not isinstance(result, InventoryCountView):
            self._on_error(RuntimeError("Unerwartete Antwort des Inventurdienstes"))
            return
        self._view = result
        self._populate(result)

    def _populate(self, view: InventoryCountView) -> None:
        self._table.setRowCount(0)
        self._line_edits.clear()
        self._note_edits.clear()
        for line in view.lines:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(line.sku))
            self._table.setItem(row, 1, QTableWidgetItem(line.title))
            self._table.setItem(row, 2, QTableWidgetItem(str(line.system_quantity)))
            counted = QLineEdit(self._table)
            counted.setPlaceholderText("Menge")
            counted.setValidator(QIntValidator(0, 2_000_000, counted))
            counted.textChanged.connect(self._update_confirm_state)
            self._table.setCellWidget(row, 3, counted)
            difference = QTableWidgetItem("-")
            difference.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 4, difference)
            note = QPlainTextEdit(self._table)
            note.setPlaceholderText("Optional")
            note.setMaximumHeight(44)
            self._table.setCellWidget(row, 5, note)
            key = str(line.id)
            self._line_edits[key] = counted
            self._note_edits[key] = note
        self._status.setText(
            f"{len(view.lines)} Artikel in {view.location_code}; bitte jede Menge erfassen."
        )
        self._update_confirm_state()

    def _update_confirm_state(self) -> None:
        ready = bool(self._view and self._view.lines)
        if ready:
            ready = all(edit.text().strip() != "" for edit in self._line_edits.values())
        self._confirm_button.setEnabled(ready and self._worker is None)

    def _confirm(self) -> None:
        view = self._view
        if view is None or self._worker is not None:
            return
        values: list[tuple[InventoryCountLineView, int, str]] = []
        for line in view.lines:
            edit = self._line_edits.get(str(line.id))
            note = self._note_edits.get(str(line.id))
            if edit is None or not edit.text().strip():
                return
            values.append((line, int(edit.text()), note.toPlainText().strip() if note else ""))

        self._set_busy(True, "Inventur wird geprueft und abgeschlossen ...")

        def job() -> InventoryCountView:
            for line, quantity, note in values:
                self._service.record_count(
                    count_id=view.id,
                    line_id=line.id,
                    counted_quantity=quantity,
                    note=note,
                )
            return self._service.confirm(count_id=view.id, actor="desktop")

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_confirmed)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()

    def _on_confirmed(self, result: object) -> None:
        if isinstance(result, InventoryCountView):
            self._view = result
            self._status.setText("Inventur bestaetigt; Differenzen wurden idempotent gebucht.")
            self._confirm_button.setEnabled(False)
            self._table.setEnabled(False)
            self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Schliessen")
        else:
            self._on_error(RuntimeError("Unerwartete Abschlussantwort des Inventurdienstes"))

    def _on_error(self, error: BaseException) -> None:
        self._status.setText(f"Fehler: {error}")
        QMessageBox.critical(self, "Inventur", str(error))

    def _on_finished(self) -> None:
        self._worker = None
        cancel = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel is not None:
            cancel.setEnabled(True)
        self._update_confirm_state()

    def _set_busy(self, busy: bool, text: str) -> None:
        self._status.setText(text)
        self._table.setEnabled(not busy)
        cancel = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel is not None:
            cancel.setEnabled(not busy)
        self._confirm_button.setEnabled(False if busy else self._confirm_button.isEnabled())


__all__ = ["InventoryCountDialog"]
