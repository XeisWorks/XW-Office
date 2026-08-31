"""PySide6 payment-clearing workflow."""
from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.clearing import (
    BookingBatchResult,
    ClearingAnalysis,
    ClearingCandidate,
    PaymentClearingService,
    ResetBatchResult,
)
from xw_office.ui.widgets.data_table import DataTable
from xw_office.ui.widgets.search_bar import SearchBar

if TYPE_CHECKING:
    from xw_office.core.container import Container


class PaymentClearingView(QWidget):
    """Analyze many payments, review exceptions, and confirm one booking batch."""

    COL_SELECT = 0
    COL_PROVIDER = 1
    COL_KIND = 2
    COL_DATE = 3
    COL_REF = 4
    COL_ORDER = 5
    COL_INVOICE = 6
    COL_CUSTOMER = 7
    COL_AMOUNT = 8
    COL_STATUS = 9
    COL_REASON = 10

    _TABLE_COLUMNS = [
        "",
        "Provider",
        "Art",
        "Datum",
        "Provider-Ref",
        "Wix",
        "sevDesk",
        "Kunde",
        "Betrag",
        "Status",
        "Hinweis",
    ]

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service = container.resolve(PaymentClearingService)
        self._worker: BackgroundWorker | None = None
        self._candidates: list[ClearingCandidate] = []
        self._visible_ids: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel("Zahlungsclearing")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)
        layout.addWidget(QLabel(self._service.describe()))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Von:"))
        self._start = QDateEdit()
        self._start.setCalendarPopup(True)
        controls.addWidget(self._start)
        controls.addWidget(QLabel("Bis:"))
        self._end = QDateEdit()
        self._end.setCalendarPopup(True)
        controls.addWidget(self._end)
        today = date.today()
        first_this_month = today.replace(day=1)
        previous_end = first_this_month.fromordinal(first_this_month.toordinal() - 1)
        previous_start = previous_end.replace(day=1)
        self._start.setDate(QDate(previous_start.year, previous_start.month, previous_start.day))
        self._end.setDate(QDate(previous_end.year, previous_end.month, previous_end.day))

        self._analyze_btn = QPushButton("Zahlungen analysieren")
        self._analyze_btn.clicked.connect(self._analyze)
        controls.addWidget(self._analyze_btn)
        self._select_all_btn = QPushButton("Alle buchbaren auswaehlen")
        self._select_all_btn.clicked.connect(lambda: self._set_all_bookable(True))
        controls.addWidget(self._select_all_btn)
        deselect = QPushButton("Auswahl aufheben")
        deselect.clicked.connect(lambda: self._set_all_bookable(False))
        controls.addWidget(deselect)
        self._reset_month_btn = QPushButton("Monat auf 100 zuruecksetzen")
        self._reset_month_btn.clicked.connect(self._reset_month_transactions)
        controls.addWidget(self._reset_month_btn)
        self._book_btn = QPushButton("Auswahl gesammelt buchen")
        self._book_btn.clicked.connect(self._book)
        controls.addWidget(self._book_btn)
        layout.addLayout(controls)

        filter_row = QHBoxLayout()
        self._search = SearchBar("Provider, Referenz, Bestellung, Rechnung oder Kunde")
        self._search.search_changed.connect(lambda _text: self._refresh_table())
        filter_row.addWidget(self._search)
        self._manual_btn = QPushButton("Offenen Fall Rechnung zuordnen")
        self._manual_btn.clicked.connect(self._assign_invoice)
        filter_row.addWidget(self._manual_btn)
        layout.addLayout(filter_row)

        self._table = DataTable(self._TABLE_COLUMNS)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.clicked.connect(self._on_table_clicked)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(self.COL_SELECT, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(self.COL_SELECT, 30)
        header.setSectionResizeMode(self.COL_CUSTOMER, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_REASON, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)

        self._summary = QLabel("Noch keine Analyse ausgefuehrt.")
        layout.addWidget(self._summary)
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self._analyze_btn.setEnabled(not running)
        self._book_btn.setEnabled(not running and bool(self._candidates))
        self._reset_month_btn.setEnabled(not running)
        self._manual_btn.setEnabled(not running and bool(self._candidates))
        self._select_all_btn.setEnabled(not running and bool(self._candidates))

    def _emit_worker_progress(self, value: int, text: str) -> None:
        worker = self._worker
        if worker is not None:
            worker.signals.progress.emit(value, text)

    def _analyze(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        start = cast(date, self._start.date().toPython())
        end = cast(date, self._end.date().toPython())
        if start > end:
            QMessageBox.warning(self, "Zahlungsclearing", "Das Startdatum liegt nach dem Enddatum.")
            return
        self._set_running(True)
        self._summary.setText("Analyse wird vorbereitet...")

        def job() -> ClearingAnalysis:
            return self._service.analyze(
                start,
                end,
                progress=self._emit_worker_progress,
            )

        self._worker = BackgroundWorker(job)
        self._worker.signals.progress.connect(
            lambda value, text: self._summary.setText(f"{text} ({value} %)")
        )
        self._worker.signals.result.connect(self._on_analysis)
        self._worker.signals.error.connect(
            lambda exc: QMessageBox.critical(self, "Zahlungsclearing", str(exc))
        )
        self._worker.signals.finished.connect(lambda: self._set_running(False))
        self._worker.start()

    def _on_analysis(self, result: object) -> None:
        if not isinstance(result, ClearingAnalysis):
            return
        self._candidates = list(result.candidates)
        self._refresh_table()
        warning = f" | Warnungen: {len(result.warnings)}" if result.warnings else ""
        self._summary.setToolTip("\n".join(result.warnings))
        self._summary.setText(
            f"{len(self._candidates)} Vorgange | {result.ready_count} automatisch buchbar | "
            f"{result.open_count} offen{warning}"
        )

    def _filtered(self) -> list[ClearingCandidate]:
        needle = self._search.text().casefold().strip()
        if not needle:
            return self._candidates
        return [
            row
            for row in self._candidates
            if needle
            in " ".join(
                (
                    row.provider,
                    row.kind.value,
                    row.provider_ref,
                    row.order_number,
                    row.invoice_number,
                    row.customer,
                    row.status.value,
                    row.reason,
                )
            ).casefold()
        ]

    def _refresh_table(self) -> None:
        rows = self._filtered()
        self._visible_ids = [row.candidate_id for row in rows]
        table_rows: list[dict[str, object]] = []
        for row in rows:
            table_rows.append(
                {
                    "": "☑" if row.selected else ("☐" if row.is_bookable else "·"),
                    "Provider": row.provider.title(),
                    "Art": row.kind.value,
                    "Datum": row.payment_date.strftime("%d.%m.%Y"),
                    "Provider-Ref": row.provider_ref,
                    "Wix": row.order_number,
                    "sevDesk": row.invoice_number,
                    "Kunde": row.customer,
                    "Betrag": f"{row.amount:.2f} EUR",
                    "Status": row.status.value,
                    "Hinweis": row.reason,
                    "__candidate_id__": row.candidate_id,
                    "__bookable__": row.is_bookable,
                    "__align__": "center",
                    "__align__Betrag": "right",
                }
            )
        self._table.set_data(table_rows)

    def _on_table_clicked(self, index: object) -> None:
        if not hasattr(index, "column") or int(index.column()) != self.COL_SELECT:
            return
        row_data = self._table.selected_row_data() or {}
        candidate_id = str(row_data.get("__candidate_id__") or "")
        if not candidate_id or not bool(row_data.get("__bookable__")):
            return
        self._candidates = [
            replace(row, selected=not row.selected) if row.candidate_id == candidate_id and row.is_bookable else row
            for row in self._candidates
        ]
        self._refresh_table()

    def _set_all_bookable(self, selected: bool) -> None:
        self._candidates = [
            replace(row, selected=selected) if row.is_bookable else replace(row, selected=False)
            for row in self._candidates
        ]
        self._refresh_table()

    def _selected_candidate(self) -> ClearingCandidate | None:
        row_index = self._table.selected_source_row()
        if row_index is None or row_index < 0 or row_index >= len(self._visible_ids):
            return None
        candidate_id = self._visible_ids[row_index]
        return next((row for row in self._candidates if row.candidate_id == candidate_id), None)

    def _assign_invoice(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            QMessageBox.information(self, "Zahlungsclearing", "Bitte zuerst eine Zeile markieren.")
            return
        invoice_number, accepted = QInputDialog.getText(
            self,
            "Rechnung zuordnen",
            "sevDesk-Rechnungsnummer:",
            text=candidate.invoice_number,
        )
        if not accepted or not invoice_number.strip():
            return
        if self._worker is not None and self._worker.isRunning():
            return
        normalized_invoice = invoice_number.strip()
        self._set_running(True)
        self._summary.setText("Rechnung wird zugeordnet...")

        def job() -> ClearingCandidate:
            return self._service.assign_invoice(candidate, normalized_invoice)

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_invoice_assigned)
        self._worker.signals.error.connect(
            lambda exc: QMessageBox.warning(self, "Zahlungsclearing", str(exc))
        )
        self._worker.signals.finished.connect(lambda: self._set_running(False))
        self._worker.start()

    def _on_invoice_assigned(self, payload: object) -> None:
        if not isinstance(payload, ClearingCandidate):
            return
        updated = payload
        candidate_id = updated.candidate_id
        self._candidates = [
            updated if row.candidate_id == candidate_id else row for row in self._candidates
        ]
        self._refresh_table()
        self._summary.setText(f"Rechnung {updated.invoice_number} wurde zugeordnet.")

    def _pick_month(self) -> date | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Monat waehlen")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Bitte den Monat fuer den Reset waehlen."))
        picker = QDateEdit()
        picker.setCalendarPopup(True)
        picker.setDisplayFormat("MMMM yyyy")
        today = date.today()
        picker.setDate(QDate(today.year, today.month, 1))
        layout.addWidget(picker)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected = cast(date, picker.date().toPython())
        return date(selected.year, selected.month, 1)

    def _reset_month_transactions(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        month_start = self._pick_month()
        if month_start is None:
            return
        month_last_day = calendar.monthrange(month_start.year, month_start.month)[1]
        month_end = date(month_start.year, month_start.month, month_last_day)
        answer = QMessageBox.question(
            self,
            "Monat auf 100 zuruecksetzen",
            f"Alle sevDesk-Transaktionen mit Status 200 im {month_start:%m.%Y} auf 100 zuruecksetzen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._set_running(True)
        self._summary.setText("Monats-Reset wird vorbereitet...")

        def job() -> ResetBatchResult:
            return self._service.reset_transactions_in_range(
                month_start,
                month_end,
                progress=self._emit_worker_progress,
            )

        self._worker = BackgroundWorker(job)
        self._worker.signals.progress.connect(
            lambda value, text: self._summary.setText(f"{text} ({value} %)")
        )
        self._worker.signals.result.connect(self._on_reset_result)
        self._worker.signals.error.connect(
            lambda exc: QMessageBox.critical(self, "Zahlungsclearing", str(exc))
        )
        self._worker.signals.finished.connect(lambda: self._set_running(False))
        self._worker.start()

    def _book(self) -> None:
        selected = [row for row in self._candidates if row.selected and row.is_bookable]
        if not selected:
            QMessageBox.information(self, "Zahlungsclearing", "Es sind keine buchbaren Zeilen ausgewaehlt.")
            return
        answer = QMessageBox.question(
            self,
            "Zahlungen gesammelt buchen",
            f"{len(selected)} Vorgange jetzt verbindlich in sevDesk buchen/importieren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._set_running(True)

        def job() -> BookingBatchResult:
            return self._service.book_selected(
                self._candidates,
                progress=self._emit_worker_progress,
            )

        self._worker = BackgroundWorker(job)
        self._worker.signals.progress.connect(
            lambda value, text: self._summary.setText(f"{text} ({value} %)")
        )
        self._worker.signals.result.connect(self._on_booking_result)
        self._worker.signals.error.connect(
            lambda exc: QMessageBox.critical(self, "Zahlungsclearing", str(exc))
        )
        self._worker.signals.finished.connect(lambda: self._set_running(False))
        self._worker.start()

    def _on_booking_result(self, result: object) -> None:
        if not isinstance(result, BookingBatchResult):
            return
        by_id = {item.candidate_id: item for item in result.items}
        self._candidates = [
            replace(
                row,
                selected=False,
                status=by_id[row.candidate_id].status,
                reason=by_id[row.candidate_id].message,
                transaction_id=by_id[row.candidate_id].transaction_id,
            )
            if row.candidate_id in by_id
            else row
            for row in self._candidates
        ]
        self._refresh_table()
        self._summary.setText(
            f"Buchung abgeschlossen: {result.success_count} erfolgreich, "
            f"{result.failure_count} fehlgeschlagen."
        )
        QMessageBox.information(self, "Zahlungsclearing", self._summary.text())

    def _on_reset_result(self, result: object) -> None:
        if not isinstance(result, ResetBatchResult):
            return
        failures = [item for item in result.items if not item.success]
        if failures:
            message = "\n".join(f"{item.transaction_id}: {item.message}" for item in failures[:20])
            self._summary.setText(
                f"Monats-Reset abgeschlossen: {result.success_count} erfolgreich, {result.failure_count} fehlgeschlagen."
            )
            QMessageBox.warning(self, "Zahlungsclearing", self._summary.text() + ("\n\n" + message if message else ""))
            return
        self._summary.setText(f"Monats-Reset abgeschlossen: {result.success_count} Transaktionen auf 100 gesetzt.")
        QMessageBox.information(self, "Zahlungsclearing", self._summary.text())

    def has_active_flow(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def request_shutdown(self) -> None:
        """Cancel an active operation; the main window waits asynchronously."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()

    def shutdown_complete(self) -> bool:
        return self._worker is None or not self._worker.isRunning()
