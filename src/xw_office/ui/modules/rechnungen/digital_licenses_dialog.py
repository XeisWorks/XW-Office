"""Dialog for external paid digital order fulfillment."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.container import Container
from xw_office.core.worker import BackgroundWorker
from xw_office.services.digital_licenses import DigitalLicenseCase, DigitalLicenseService


class DigitalLicensesDialog(QDialog):
    """Paid digital sheet-music license fulfillment queue."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: DigitalLicenseService = container.resolve(DigitalLicenseService)
        self._cases: list[DigitalLicenseCase] = []
        self._loaded_once = False
        self._load_worker: BackgroundWorker | None = None
        self._action_worker: BackgroundWorker | None = None
        self._prepared_files: list[Path] = []
        self._draft_worker: BackgroundWorker | None = None
        self._build_ui()
        QTimer.singleShot(0, self._load_cases)

    def _build_ui(self) -> None:
        self.setWindowTitle("Digitale Lieferung")
        self.setMinimumSize(1020, 650)

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self._status = QLabel("-")
        top.addWidget(self._status, stretch=1)
        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(self._load_cases)
        top.addWidget(self._btn_refresh)
        root.addLayout(top)

        splitter = QSplitter()
        left = QWidget()
        left_lay = QVBoxLayout(left)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._show_selected_case)
        left_lay.addWidget(self._list)
        splitter.addWidget(left)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        self._meta = QLabel("Keine externe Bestellung ausgewaehlt")
        self._meta.setWordWrap(True)
        right_lay.addWidget(self._meta)
        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        right_lay.addWidget(self._details, stretch=1)

        row = QHBoxLayout()
        self._btn_pick_missing = QPushButton("Fehlende Druck-PDF zuordnen")
        self._btn_pick_missing.clicked.connect(self._pick_missing_pdf)
        row.addWidget(self._btn_pick_missing)
        self._btn_prepare = QPushButton("PDFs erstellen und pruefen")
        self._btn_prepare.clicked.connect(self._prepare_selected)
        row.addWidget(self._btn_prepare)
        row.addStretch(1)
        self._btn_done = QPushButton("E-Mail wurde gesendet – abschliessen")
        self._btn_done.clicked.connect(self._mark_selected_done)
        row.addWidget(self._btn_done)
        right_lay.addLayout(row)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def open_count(self) -> int:
        if self._loaded_once:
            return len(self._cases)
        return self._service.open_count(limit=30, use_cache=True)

    def _load_cases(self) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self._status.setText("Lade externe Bestellungen...")
        self._load_worker = BackgroundWorker(self._service.list_open_cases)
        self._load_worker.signals.result.connect(self._on_cases_loaded)
        self._load_worker.signals.error.connect(self._on_error)
        self._load_worker.signals.finished.connect(lambda: setattr(self, "_load_worker", None))
        self._load_worker.start()

    def _on_cases_loaded(self, payload: object) -> None:
        self._cases = list(payload) if isinstance(payload, list) else []
        self._loaded_once = True
        self._list.clear()
        for case in self._cases:
            item = QListWidgetItem(f"{case.order_reference or '-'} | {case.customer_name or '-'}")
            item.setToolTip(case.invoice_number or case.invoice_id)
            self._list.addItem(item)
        self._status.setText(f"Offen: {len(self._cases)}")
        if self._cases:
            self._list.setCurrentRow(0)
        else:
            self._show_selected_case(-1)

    def _selected_case(self) -> DigitalLicenseCase | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._cases):
            return self._cases[row]
        return None

    def _show_selected_case(self, _row: int) -> None:
        case = self._selected_case()
        enabled = case is not None
        self._btn_pick_missing.setEnabled(enabled)
        self._btn_prepare.setEnabled(enabled)
        self._btn_done.setEnabled(enabled)
        if case is None:
            self._meta.setText("Keine externe Bestellung ausgewaehlt")
            self._details.clear()
            return
        self._meta.setText(
            f"Order: {case.order_reference or '-'} | Rechnung: {case.invoice_number or case.invoice_id}\n"
            f"Kunde: {case.customer_name or '-'} | E-Mail: {case.customer_email or '-'}"
        )
        self._btn_done.setEnabled(enabled and case.state == "DRAFT_READY")
        self._btn_prepare.setText(
            "Outlook-Entwurf oeffnen" if enabled and case.state == "DRAFT_READY" else "PDFs erstellen und pruefen"
        )
        lines = []
        for line in case.lines:
            status = "FEHLT" if line.missing_print_file else "OK"
            lines.append(
                f"{status} | {line.quantity}x {line.name}\n"
                f"SKU: {line.sku or '-'}\n"
                f"Druckpfad: {line.print_file_path or '-'}"
            )
        self._details.setPlainText("\n\n".join(lines))

    def _pick_missing_pdf(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        missing = next((line for line in case.lines if line.missing_print_file), None)
        if missing is None:
            QMessageBox.information(self, "Druck-PDF", "Alle Produkte haben bereits einen gueltigen Druckpfad.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Druck-PDF zuordnen", "", "PDF (*.pdf)")
        if not path:
            return
        if not Path(path).is_file():
            QMessageBox.warning(self, "Druck-PDF", "Die Datei wurde nicht gefunden.")
            return
        self._service.apply_print_path(missing.sku, path)
        missing.print_file_path = path
        missing.missing_print_file = False
        self._show_selected_case(self._list.currentRow())

    def _prepare_selected(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        if case.state == "DRAFT_READY":
            self._run_action(
                lambda: self._service.reopen_outlook_draft(case),
                "Outlook-Entwurf wird geoeffnet...",
            )
            return
        missing = [line for line in case.lines if line.missing_print_file]
        if missing:
            QMessageBox.warning(self, "Externe Bestellung", "Bitte zuerst alle fehlenden Druck-PDFs zuordnen.")
            return
        if self._draft_worker is not None and self._draft_worker.isRunning():
            return
        self._status.setText("Personalisierte PDFs werden erstellt...")
        worker = BackgroundWorker(lambda: self._service.prepare_license_files(case))
        worker.signals.result.connect(self._on_files_prepared)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(lambda: setattr(self, "_draft_worker", None))
        self._draft_worker = worker
        worker.start()

    def _on_files_prepared(self, payload: object) -> None:
        files = [Path(item) for item in payload] if isinstance(payload, list) else []
        if not files:
            self._on_error(RuntimeError("Keine Lizenz-PDF erzeugt"))
            return
        self._prepared_files = files
        for path in files:
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(path))  # type: ignore[attr-defined]
            except OSError as exc:
                self._on_error(RuntimeError(f"PDF konnte nicht geoeffnet werden: {path}: {exc}"))
                return
        if QMessageBox.question(
            self,
            "PDF-Kontrolle",
            "Die personalisierten PDFs wurden geoeffnet. Sind Name, Seiten und Vollstaendigkeit korrekt?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ) != QMessageBox.StandardButton.Yes:
            self._status.setText("PDF-Kontrolle zurueckgestellt – Fall bleibt offen.")
            return
        case = self._selected_case()
        if case is None:
            return
        self._status.setText("Outlook-Entwurf wird gespeichert...")
        worker = BackgroundWorker(lambda: self._service.create_outlook_draft(case, self._prepared_files))
        worker.signals.result.connect(self._on_draft_created)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(lambda: setattr(self, "_draft_worker", None))
        self._draft_worker = worker
        worker.start()

    def _on_draft_created(self, _payload: object) -> None:
        case = self._selected_case()
        if case is not None:
            case.state = "DRAFT_READY"
            self._btn_done.setEnabled(True)
        self._status.setText("Outlook-Entwurf gespeichert. Bitte in Outlook pruefen und senden.")
        QMessageBox.information(
            self,
            "Outlook-Entwurf",
            "Der Entwurf wurde gespeichert und geoeffnet. Sende ihn in Outlook und bestaetige danach hier den Versand.",
        )

    def _mark_selected_done(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        if case.state != "DRAFT_READY":
            QMessageBox.warning(
                self,
                "Externe Bestellung",
                "Bitte zuerst die PDFs kontrollieren und den Outlook-Entwurf speichern.",
            )
            return
        if QMessageBox.question(
            self,
            "Externe Bestellung",
            "Hast du die E-Mail mit Rechnung und allen Noten-PDFs gesendet?\n\nDanach wird Wix-Fulfillment abgeschlossen.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._run_action(lambda: self._service.mark_done(case), "Markiere Versand als erledigt...")

    def _run_action(self, job: object, message: str) -> None:
        if self._action_worker is not None and self._action_worker.isRunning():
            return
        self._status.setText(message)
        self._action_worker = BackgroundWorker(job)  # type: ignore[arg-type]
        self._action_worker.signals.result.connect(lambda _payload: self._load_cases())
        self._action_worker.signals.error.connect(self._on_error)
        self._action_worker.signals.finished.connect(lambda: setattr(self, "_action_worker", None))
        self._action_worker.start()

    def _on_error(self, exc: Exception) -> None:
        self._status.setText("Fehler")
        QMessageBox.warning(self, "Externe Bestellung", str(exc))
