"""Dialog for external paid digital order fulfillment."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
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
from xw_office.services.digital_licenses import (
    DigitalLicenseCase,
    DigitalLicenseLine,
    DigitalLicenseService,
)


class DigitalLicensesDialog(QDialog):
    """Paid digital sheet-music license fulfillment queue."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: DigitalLicenseService = container.resolve(DigitalLicenseService)
        self._cases: list[DigitalLicenseCase] = []
        self._open_case_count = 0
        self._load_worker: BackgroundWorker | None = None
        self._action_worker: BackgroundWorker | None = None
        self._prepared_files: list[Path] = []
        self._draft_worker: BackgroundWorker | None = None
        self._license_preparing = False
        self._closing = False
        self._build_ui()
        QTimer.singleShot(0, self._load_cases)

    def reject(self) -> None:
        if self._has_active_write():
            return
        self._closing = True
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._has_active_write():
            event.ignore()
            return
        self._closing = True
        super().closeEvent(event)

    def _has_active_write(self) -> bool:
        return self._license_preparing or (
            self._action_worker is not None and self._action_worker.isRunning()
        )

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
        return self._open_case_count

    def _load_cases(self) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self._status.setText("Lade externe Bestellungen...")
        worker = BackgroundWorker(self._service.list_open_cases)
        self._load_worker = worker
        worker.signals.result.connect(self._on_cases_loaded)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(lambda current=worker: self._on_load_worker_finished(current))
        worker.start()

    def _on_load_worker_finished(self, worker: BackgroundWorker) -> None:
        if self._load_worker is not worker:
            return
        self._load_worker = None

    def _on_cases_loaded(self, payload: object) -> None:
        if self._closing:
            return
        self._cases = list(payload) if isinstance(payload, list) else []
        self._open_case_count = len(self._cases)
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
        enabled = case is not None and not self._license_preparing
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
        self._status.setText("Druck-PDF-Zuordnung wird gespeichert...")
        self._start_draft_job(
            lambda: self._service.apply_print_path(missing.sku, path),
            lambda _payload: self._on_print_path_applied(missing, path),
        )

    def _on_print_path_applied(
        self,
        line: DigitalLicenseLine,
        path: str,
    ) -> None:
        line.print_file_path = path
        line.missing_print_file = False
        self._status.setText("Druck-PDF-Zuordnung gespeichert.")

    def _prepare_selected(self) -> None:
        if self._license_preparing or (
            self._action_worker is not None and self._action_worker.isRunning()
        ):
            return
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
        self._start_draft_job(
            lambda: self._service.prepare_license_files(case),
            lambda payload: self._on_files_prepared(payload, case),
        )

    def _on_files_prepared(self, payload: object, case: DigitalLicenseCase) -> None:
        files = [Path(item) for item in payload] if isinstance(payload, list) else []
        if not files:
            self._on_error(RuntimeError("Keine Lizenz-PDF erzeugt"))
            return
        self._prepared_files = files
        for path in files:
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(path))
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
        self._status.setText("Outlook-Entwurf wird gespeichert...")
        self._start_draft_job(
            lambda: self._service.create_outlook_draft(case, files),
            lambda payload: self._on_draft_created(payload, case),
        )

    def _start_draft_job(
        self,
        job: Callable[[], object],
        on_result: Callable[[object], None],
    ) -> None:
        self._license_preparing = True
        self._list.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._show_selected_case(self._list.currentRow())
        worker = BackgroundWorker(job)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(lambda: self._on_draft_worker_finished(worker))
        self._draft_worker = worker
        worker.start()

    def _on_draft_worker_finished(self, worker: BackgroundWorker) -> None:
        if self._draft_worker is not worker:
            return
        self._draft_worker = None
        self._license_preparing = False
        self._list.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._show_selected_case(self._list.currentRow())

    def _on_draft_created(self, _payload: object, case: DigitalLicenseCase) -> None:
        case.state = "DRAFT_READY"
        self._status.setText("Outlook-Entwurf gespeichert. Bitte in Outlook pruefen und senden.")
        QMessageBox.information(
            self,
            "Outlook-Entwurf",
            "Der Entwurf wurde gespeichert und geoeffnet. Sende ihn in Outlook und bestaetige danach hier den Versand.",
        )

    def _mark_selected_done(self) -> None:
        if self._license_preparing:
            return
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

        def job() -> int:
            self._service.mark_done(case)
            return self._service.open_count()

        self._run_action(job, "Markiere Versand als erledigt...", self._on_mark_done_finished)

    def _on_mark_done_finished(self, payload: object) -> None:
        if type(payload) is not int:
            self._status.setText("Abschlussstatus unklar – offene Bestellungen werden neu geladen…")
            self._load_cases()
            return
        remaining = payload
        self._open_case_count = remaining
        if remaining <= 0:
            QTimer.singleShot(0, self.accept)
            return
        self._load_cases()

    def _run_action(
        self,
        job: object,
        message: str,
        on_result: Callable[[object], None] | None = None,
    ) -> None:
        if self._license_preparing or (
            self._action_worker is not None and self._action_worker.isRunning()
        ):
            return
        self._status.setText(message)
        worker = BackgroundWorker(job)  # type: ignore[arg-type]
        self._action_worker = worker
        result_handler = on_result or (lambda _payload: self._load_cases())
        worker.signals.result.connect(result_handler)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(lambda current=worker: self._on_action_worker_finished(current))
        worker.start()

    def _on_action_worker_finished(self, worker: BackgroundWorker) -> None:
        if self._action_worker is not worker:
            return
        self._action_worker = None

    def _on_error(self, exc: Exception) -> None:
        if self._closing:
            return
        self._status.setText("Fehler")
        QMessageBox.warning(self, "Externe Bestellung", str(exc))
