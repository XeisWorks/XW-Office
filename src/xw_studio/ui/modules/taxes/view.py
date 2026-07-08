"""Steuern module — UVA, Clearing, Ausgaben with non-blocking actions."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.clearing.service import ClearingRow, PaymentClearingService
from xw_studio.services.expenses.service import ExpenseAuditService, ExpenseRow
from xw_studio.services.finanzonline import OssQuarterResult, OssService, OssXmlExport, UvaService, UvaSubmitResult
from xw_studio.ui.widgets.search_bar import SearchBar

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_UVA_WARNING_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Zahlung außerhalb UVA-Monat", ("Zahlung liegt außerhalb des UVA-Monats",)),
    ("Fehlender Zahlungsnachweis", ("Ohne Zahlungsnachweis im IST-Modus",)),
    ("Offen/Entwurf ignoriert", ("Offener/Entwurfs-Beleg",)),
    ("Storno ignoriert", ("Stornierter Beleg",)),
    ("Teilzahlungen", ("Teilzahlung anteilig",)),
    ("Gutschrift-Prüfung", ("Gutschrift ohne Referenzrechnung",)),
    ("Duplikate", ("Duplikat-Beleg",)),
    (
        "Nicht in AT-UVA übernommen",
        ("Nicht in AT-UVA übernommen", "Ausländische Vorsteuer nicht in AT-UVA übernommen"),
    ),
)


def _render_grouped_uva_warnings(warnings: list[str]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        text = str(warning).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)

    if not cleaned:
        return ""

    grouped: dict[str, list[str]] = {name: [] for name, _ in _UVA_WARNING_GROUPS}
    others: list[str] = []

    for warning in cleaned:
        assigned = False
        lowered = warning.lower()
        for group_name, markers in _UVA_WARNING_GROUPS:
            if any(marker.lower() in lowered for marker in markers):
                grouped[group_name].append(warning)
                assigned = True
                break
        if not assigned:
            others.append(warning)

    total = len(cleaned)
    lines = [f"Hinweise (gruppiert, {total}):"]
    for group_name, _markers in _UVA_WARNING_GROUPS:
        items = grouped[group_name]
        if not items:
            continue
        lines.append(f"- {group_name} ({len(items)}):")
        lines.extend(f"  - {item}" for item in items)
    if others:
        lines.append(f"- Sonstige ({len(others)}):")
        lines.extend(f"  - {item}" for item in others)
    return "\n".join(lines)


class TaxesView(QWidget):
    """UVA | Clearing | Ausgaben — calls services off the UI thread."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._uva_preview_worker: BackgroundWorker | None = None
        self._uva_submit_worker: BackgroundWorker | None = None
        self._oss_worker: BackgroundWorker | None = None
        self._clearing_worker: BackgroundWorker | None = None
        self._expenses_worker: BackgroundWorker | None = None
        self._clearing_rows: list[ClearingRow] = []
        self._expenses_rows: list[ExpenseRow] = []
        self._uva_progress_bar: QProgressBar | None = None
        self._uva_progress_label: QLabel | None = None
        self._uva_preview_button: QPushButton | None = None
        self._uva_submit_button: QPushButton | None = None
        self._uva_progress_text = ""
        self._uva_progress_timer = QTimer(self)
        self._uva_progress_timer.setInterval(250)
        self._uva_progress_timer.timeout.connect(self._tick_uva_progress)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        tabs = QTabWidget()

        tabs.addTab(self._build_uva_tab(), "UVA")
        tabs.addTab(self._build_oss_tab(), "EU-OSS")
        tabs.addTab(self._build_expenses_tab(), "Ausgaben")
        outer.addWidget(tabs)

    def _build_uva_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        info = QPlainTextEdit()
        uva: UvaService = self._container.resolve(UvaService)
        info.setPlainText(uva.describe_capabilities())
        info.setReadOnly(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Jahr:"))
        year = QSpinBox()
        year.setRange(2000, 2100)
        year.setValue(2026)
        row.addWidget(year)
        row.addWidget(QLabel("Monat:"))
        month = QSpinBox()
        month.setRange(1, 12)
        month.setValue(1)
        row.addWidget(month)
        row.addStretch()
        layout.addLayout(row)

        self._uva_progress_label = QLabel("Bereit")
        self._uva_progress_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self._uva_progress_label)

        self._uva_progress_bar = QProgressBar()
        self._uva_progress_bar.setRange(0, 100)
        self._uva_progress_bar.setValue(0)
        self._uva_progress_bar.hide()
        layout.addWidget(self._uva_progress_bar)

        preview = QPushButton("UVA berechnen")
        submit = QPushButton("UVA + ZM an FinanzOnline senden")
        self._uva_preview_button = preview
        self._uva_submit_button = submit

        def on_progress(value: int, text: str) -> None:
            self._set_uva_progress(value, text)

        def on_preview() -> None:
            if self._uva_preview_worker is not None and self._uva_preview_worker.isRunning():
                return
            if self._uva_submit_worker is not None and self._uva_submit_worker.isRunning():
                return

            self._set_uva_busy(True)
            self._set_uva_progress(5, "UVA-Berechnung wird vorbereitet...")

            def job() -> dict[str, object]:
                self._emit_uva_preview_progress(20, "UVA-Daten werden aus sevDesk geladen...")
                payload = uva.calculate_month(year.value(), month.value())
                self._emit_uva_preview_progress(100, "UVA-Berechnung abgeschlossen")
                return payload

            self._uva_preview_worker = BackgroundWorker(job)

            def on_preview_result(payload: object) -> None:
                if not isinstance(payload, dict):
                    info.appendPlainText("\n\nKeine gueltige UVA-Antwort erhalten.")
                    return
                preview_text = str(payload.get("preview_text") or "").strip()
                kennzahlen_text = str(payload.get("kennzahlen_text") or "").strip()
                zm_text = str(payload.get("zm_text") or "").strip()
                warnings_value = payload.get("warnings")
                warning_lines = [
                    str(item)
                    for item in warnings_value
                    if isinstance(item, str)
                ] if isinstance(warnings_value, list) else []
                grouped_warnings_text = _render_grouped_uva_warnings(warning_lines)
                combined = "\n\n".join(
                    part
                    for part in [preview_text, kennzahlen_text, grouped_warnings_text, zm_text]
                    if part
                )
                if combined:
                    info.appendPlainText("\n\n" + combined)
                    return
                info.appendPlainText("\n\n" + repr(payload))

            self._uva_preview_worker.signals.progress.connect(on_progress)
            self._uva_preview_worker.signals.result.connect(on_preview_result)
            self._uva_preview_worker.signals.error.connect(
                lambda exc: QMessageBox.warning(self, "UVA", f"Fehler: {exc}")
            )

            def on_preview_finished() -> None:
                self._uva_preview_worker = None
                self._set_uva_busy(False)
                self._container.resolve(AppSignals).status_message.emit("UVA-Berechnung beendet", 3000)

            self._uva_preview_worker.signals.finished.connect(on_preview_finished)
            self._uva_preview_worker.start()

        def on_submit() -> None:
            if self._uva_submit_worker is not None and self._uva_submit_worker.isRunning():
                return
            if self._uva_preview_worker is not None and self._uva_preview_worker.isRunning():
                return

            self._set_uva_busy(True)
            self._set_uva_progress(5, "UVA/U13 wird vorbereitet...")

            def job() -> UvaSubmitResult:
                self._emit_uva_submit_progress(20, "UVA-Payload wird erstellt...")
                self._emit_uva_submit_progress(45, "UVA wird an FinanzOnline gesendet...")
                result = uva.submit_month(year.value(), month.value())
                self._emit_uva_submit_progress(100, "Sendevorgang abgeschlossen")
                return result

            self._uva_submit_worker = BackgroundWorker(job)

            def on_uva_result(res: object) -> None:
                if not isinstance(res, UvaSubmitResult):
                    QMessageBox.warning(self, "UVA + ZM", "Keine gueltige Antwort erhalten.")
                    return
                text = res.message + (f" (Ref. {res.reference_id})" if res.reference_id else "")
                if res.zm_ok is not None:
                    zm_text = res.zm_message or ("ZM erfolgreich" if res.zm_ok else "ZM fehlgeschlagen")
                    if res.zm_reference_id:
                        zm_text += f" (Ref. {res.zm_reference_id})"
                    text = f"U30: {text}\nZM/U13: {zm_text}"
                if res.ok:
                    QMessageBox.information(self, "UVA + ZM", f"Erfolg: {text}")
                else:
                    QMessageBox.warning(self, "UVA + ZM", f"Fehler: {text}")

            self._uva_submit_worker.signals.progress.connect(on_progress)
            self._uva_submit_worker.signals.result.connect(on_uva_result)
            self._uva_submit_worker.signals.error.connect(
                lambda exc: QMessageBox.warning(
                    self,
                    "UVA + ZM",
                    f"Fehler: {exc}",
                )
            )

            def on_submit_finished() -> None:
                self._uva_submit_worker = None
                self._set_uva_busy(False)
                self._container.resolve(AppSignals).status_message.emit("UVA-Job beendet", 3000)

            self._uva_submit_worker.signals.finished.connect(on_submit_finished)
            self._uva_submit_worker.start()

        preview.clicked.connect(on_preview)
        submit.clicked.connect(on_submit)
        layout.addWidget(preview)
        layout.addWidget(submit)
        return page

    def _set_uva_busy(self, busy: bool) -> None:
        for button in (self._uva_preview_button, self._uva_submit_button):
            if button is not None:
                button.setEnabled(not busy)
        if self._uva_progress_bar is not None:
            self._uva_progress_bar.setVisible(busy)
            if busy:
                if not self._uva_progress_timer.isActive():
                    self._uva_progress_timer.start()
            else:
                self._uva_progress_timer.stop()
                self._uva_progress_bar.setValue(0)
        if not busy and self._uva_progress_label is not None:
            self._uva_progress_label.setText("Bereit")
            self._uva_progress_text = ""

    def _set_uva_progress(self, value: int, text: str) -> None:
        percent = max(0, min(100, int(value)))
        if self._uva_progress_bar is not None:
            self._uva_progress_bar.setValue(percent)
        self._uva_progress_text = text or self._uva_progress_text
        if self._uva_progress_label is not None and text:
            self._uva_progress_label.setText(f"{text} ({percent} %)")
        if text:
            self._container.resolve(AppSignals).status_message.emit(f"{text} ({percent} %)", 2500)

    def _tick_uva_progress(self) -> None:
        if self._uva_progress_bar is None:
            return
        running = (
            (self._uva_preview_worker is not None and self._uva_preview_worker.isRunning())
            or (self._uva_submit_worker is not None and self._uva_submit_worker.isRunning())
        )
        if not running:
            self._uva_progress_timer.stop()
            return
        current = self._uva_progress_bar.value()
        if current >= 90:
            return
        next_value = current + 1
        self._uva_progress_bar.setValue(next_value)
        if self._uva_progress_label is not None and self._uva_progress_text:
            self._uva_progress_label.setText(f"{self._uva_progress_text} ({next_value} %)")

    def _emit_uva_preview_progress(self, value: int, text: str) -> None:
        worker = self._uva_preview_worker
        if worker is not None:
            worker.signals.progress.emit(value, text)

    def _emit_uva_submit_progress(self, value: int, text: str) -> None:
        worker = self._uva_submit_worker
        if worker is not None:
            worker.signals.progress.emit(value, text)

    def _build_oss_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        oss: OssService = self._container.resolve(OssService)

        info = QPlainTextEdit()
        info.setReadOnly(True)
        info.setPlainText(oss.describe_capabilities())
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Jahr:"))
        year = QSpinBox()
        year.setRange(2021, 2100)
        year.setValue(2026)
        row.addWidget(year)
        row.addWidget(QLabel("Quartal:"))
        quarter = QComboBox()
        quarter.addItem("Q1", 1)
        quarter.addItem("Q2", 2)
        quarter.addItem("Q3", 3)
        quarter.addItem("Q4", 4)
        row.addWidget(quarter)
        row.addStretch()
        layout.addLayout(row)

        form = QHBoxLayout()
        form.addWidget(QLabel("OSS-ID:"))
        oss_id = QLineEdit()
        oss_id.setPlaceholderText("z. B. ATU...")
        default_oss_id = str(self._container.config.finanzonline.hersteller_id or "").strip()
        if default_oss_id.upper().startswith("ATU"):
            oss_id.setText(default_oss_id)
        form.addWidget(oss_id)
        form.addWidget(QLabel("UID Fixed Est. (optional):"))
        uid_fixed_est = QLineEdit()
        uid_fixed_est.setPlaceholderText("optional")
        form.addWidget(uid_fixed_est)
        layout.addLayout(form)

        preview_box = QPlainTextEdit()
        preview_box.setReadOnly(True)
        layout.addWidget(preview_box)

        buttons = QHBoxLayout()
        preview = QPushButton("EU-OSS berechnen")
        export = QPushButton("EU-OSS XML speichern")
        portal = QPushButton("Testportal oeffnen")
        buttons.addWidget(preview)
        buttons.addWidget(export)
        buttons.addWidget(portal)
        buttons.addStretch()
        layout.addLayout(buttons)

        def selected_quarter() -> int:
            value = quarter.currentData()
            return int(value) if value is not None else 1

        def on_preview() -> None:
            def job() -> OssQuarterResult:
                return oss.calculate_quarter(year.value(), selected_quarter())

            self._oss_worker = BackgroundWorker(job)

            def on_result(res: object) -> None:
                if not isinstance(res, OssQuarterResult):
                    return
                preview_box.setPlainText(oss.render_preview_text(res))

            self._oss_worker.signals.result.connect(on_result)
            self._oss_worker.signals.error.connect(
                lambda exc: QMessageBox.information(self, "EU-OSS", f"Fehler: {exc}")
            )
            self._oss_worker.start()

        def on_export() -> None:
            current_oss_id = oss_id.text().strip()
            if not current_oss_id:
                QMessageBox.information(self, "EU-OSS", "Bitte zuerst eine OSS-ID eintragen.")
                return

            def job() -> OssXmlExport:
                return oss.build_xml_export(
                    year.value(),
                    selected_quarter(),
                    oss_id=current_oss_id,
                    uid_fixed_est=uid_fixed_est.text().strip(),
                )

            self._oss_worker = BackgroundWorker(job)

            def on_result(res: object) -> None:
                if not isinstance(res, OssXmlExport):
                    return
                selected_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "EU-OSS XML speichern",
                    res.file_name,
                    "XML (*.xml);;Alle Dateien (*.*)",
                )
                if not selected_path:
                    return
                Path(selected_path).write_text(res.xml_payload, encoding="utf-8")
                preview_box.setPlainText(res.xml_payload)
                QMessageBox.information(
                    self,
                    "EU-OSS",
                    f"XML gespeichert:\n{selected_path}\n\nDanach im EU-OSS-Portal hochladen und pruefen.",
                )

            self._oss_worker.signals.result.connect(on_result)
            self._oss_worker.signals.error.connect(
                lambda exc: QMessageBox.information(self, "EU-OSS", f"Fehler: {exc}")
            )
            self._oss_worker.start()

        def on_portal() -> None:
            if not QDesktopServices.openUrl(QUrl(oss.portal_url(test_mode=True))):
                QMessageBox.warning(self, "EU-OSS", "Das Testportal konnte nicht geoeffnet werden.")

        preview.clicked.connect(on_preview)
        export.clicked.connect(on_export)
        portal.clicked.connect(on_portal)
        return page

    def _build_clearing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        svc: PaymentClearingService = self._container.resolve(PaymentClearingService)
        box = QGroupBox("Zahlungsclearing")
        bl = QVBoxLayout(box)
        bl.addWidget(QLabel(svc.describe()))

        filters = QHBoxLayout()
        self._clearing_search = SearchBar("Suchen (mind. 3 Zeichen)…")
        self._clearing_search.setPlaceholderText("Suchen (Ref, Kunde, Betrag, Hinweis)")
        self._clearing_search.search_changed.connect(lambda _t: self._apply_clearing_filter())
        self._clearing_search.set_suggestion_provider(self._clearing_search_suggestions)
        filters.addWidget(self._clearing_search)
        self._clearing_status_filter = QComboBox()
        self._clearing_status_filter.addItems(["", "offen", "authorized", "zugeordnet", "done"])
        self._clearing_status_filter.currentTextChanged.connect(lambda _t: self._apply_clearing_filter())
        filters.addWidget(self._clearing_status_filter)
        refresh = QPushButton("Neu laden")
        refresh.clicked.connect(self._load_clearing_rows)
        filters.addWidget(refresh)
        export = QPushButton("CSV exportieren")
        export.clicked.connect(self._export_clearing_csv)
        filters.addWidget(export)
        bl.addLayout(filters)

        self._clearing_table = QTableWidget(0, 5)
        self._clearing_table.setHorizontalHeaderLabels(["Ref", "Kunde", "Betrag", "Status", "Hinweis"])
        self._clearing_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._clearing_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._clearing_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._clearing_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        bl.addWidget(self._clearing_table)

        self._clearing_status = QLabel("Noch nicht geladen.")
        bl.addWidget(self._clearing_status)
        layout.addWidget(box)
        layout.addStretch()
        self._load_clearing_rows()
        return page

    def _build_expenses_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        svc: ExpenseAuditService = self._container.resolve(ExpenseAuditService)
        box = QGroupBox("Ausgaben")
        bl = QVBoxLayout(box)
        bl.addWidget(QLabel(svc.describe()))

        filters = QHBoxLayout()
        self._expenses_search = SearchBar("Suchen (mind. 3 Zeichen)…")
        self._expenses_search.setPlaceholderText("Suchen (Ref, Lieferant, Kategorie, Hinweis)")
        self._expenses_search.search_changed.connect(lambda _t: self._apply_expenses_filter())
        self._expenses_search.set_suggestion_provider(self._expenses_search_suggestions)
        filters.addWidget(self._expenses_search)
        self._expenses_status_filter = QComboBox()
        self._expenses_status_filter.addItems(["", "offen", "in_pruefung", "gebucht", "done"])
        self._expenses_status_filter.currentTextChanged.connect(lambda _t: self._apply_expenses_filter())
        filters.addWidget(self._expenses_status_filter)
        refresh = QPushButton("Neu laden")
        refresh.clicked.connect(self._load_expense_rows)
        filters.addWidget(refresh)
        export = QPushButton("CSV exportieren")
        export.clicked.connect(self._export_expenses_csv)
        filters.addWidget(export)
        bl.addLayout(filters)

        self._expenses_table = QTableWidget(0, 6)
        self._expenses_table.setHorizontalHeaderLabels(
            ["Ref", "Lieferant", "Brutto", "Kategorie", "Status", "Hinweis"]
        )
        self._expenses_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._expenses_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._expenses_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._expenses_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        bl.addWidget(self._expenses_table)

        self._expenses_status = QLabel("Noch nicht geladen.")
        bl.addWidget(self._expenses_status)

        layout.addWidget(box)
        layout.addStretch()
        self._load_expense_rows()
        return page

    def _load_clearing_rows(self) -> None:
        if self._clearing_worker is not None and self._clearing_worker.isRunning():
            return
        svc: PaymentClearingService = self._container.resolve(PaymentClearingService)
        self._clearing_status.setText("Lade Clearing-Daten...")

        def job() -> list[ClearingRow]:
            return svc.list_pending()

        self._clearing_worker = BackgroundWorker(job)
        self._clearing_worker.signals.result.connect(self._on_clearing_loaded)
        self._clearing_worker.signals.error.connect(
            lambda exc: QMessageBox.warning(self, "Clearing", str(exc))
        )
        self._clearing_worker.start()

    def _on_clearing_loaded(self, rows: object) -> None:
        if not isinstance(rows, list):
            return
        self._clearing_rows = [row for row in rows if isinstance(row, ClearingRow)]
        self._clearing_search.refresh_suggestions()
        self._apply_clearing_filter()

    def _apply_clearing_filter(self) -> None:
        svc: PaymentClearingService = self._container.resolve(PaymentClearingService)
        filtered = svc.filter_rows(
            self._clearing_rows,
            needle=self._clearing_search.text(),
            status=self._clearing_status_filter.currentText(),
        )
        self._populate_clearing_table(filtered)
        self._clearing_status.setText(f"{len(filtered)} von {len(self._clearing_rows)} Eintraegen")

    def _populate_clearing_table(self, rows: list[ClearingRow]) -> None:
        tbl = self._clearing_table
        tbl.setRowCount(0)
        for row in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(row.ref))
            tbl.setItem(r, 1, QTableWidgetItem(row.customer))
            tbl.setItem(r, 2, QTableWidgetItem(row.amount))
            tbl.setItem(r, 3, QTableWidgetItem(row.status))
            tbl.setItem(r, 4, QTableWidgetItem(row.note))

    def _export_clearing_csv(self) -> None:
        svc: PaymentClearingService = self._container.resolve(PaymentClearingService)
        rows = svc.filter_rows(
            self._clearing_rows,
            needle=self._clearing_search.text(),
            status=self._clearing_status_filter.currentText(),
        )
        payload = svc.export_csv(rows)
        path, _ = QFileDialog.getSaveFileName(self, "Clearing CSV speichern", "clearing.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(payload)
        QMessageBox.information(self, "Clearing", f"CSV exportiert:\n{path}")

    def _load_expense_rows(self) -> None:
        if self._expenses_worker is not None and self._expenses_worker.isRunning():
            return
        svc: ExpenseAuditService = self._container.resolve(ExpenseAuditService)
        self._expenses_status.setText("Lade Ausgaben...")

        def job() -> list[ExpenseRow]:
            return svc.list_open()

        self._expenses_worker = BackgroundWorker(job)
        self._expenses_worker.signals.result.connect(self._on_expenses_loaded)
        self._expenses_worker.signals.error.connect(
            lambda exc: QMessageBox.warning(self, "Ausgaben", str(exc))
        )
        self._expenses_worker.start()

    def _on_expenses_loaded(self, rows: object) -> None:
        if not isinstance(rows, list):
            return
        self._expenses_rows = [row for row in rows if isinstance(row, ExpenseRow)]
        self._expenses_search.refresh_suggestions()
        self._apply_expenses_filter()

    def _clearing_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 3:
            return []
        out: list[str] = []
        for row in self._clearing_rows:
            hay = f"{row.ref} {row.customer} {row.amount} {row.status} {row.note}".lower()
            if q in hay:
                out.append(f"{row.ref} - {row.customer}")
        return out

    def _expenses_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 3:
            return []
        out: list[str] = []
        for row in self._expenses_rows:
            hay = f"{row.ref} {row.supplier} {row.category} {row.status} {row.note}".lower()
            if q in hay:
                out.append(f"{row.ref} - {row.supplier}")
        return out

    def _apply_expenses_filter(self) -> None:
        svc: ExpenseAuditService = self._container.resolve(ExpenseAuditService)
        filtered = svc.filter_rows(
            self._expenses_rows,
            needle=self._expenses_search.text(),
            status=self._expenses_status_filter.currentText(),
        )
        self._populate_expenses_table(filtered)
        self._expenses_status.setText(f"{len(filtered)} von {len(self._expenses_rows)} Eintraegen")

    def _populate_expenses_table(self, rows: list[ExpenseRow]) -> None:
        tbl = self._expenses_table
        tbl.setRowCount(0)
        for row in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(row.ref))
            tbl.setItem(r, 1, QTableWidgetItem(row.supplier))
            tbl.setItem(r, 2, QTableWidgetItem(row.gross_amount))
            tbl.setItem(r, 3, QTableWidgetItem(row.category))
            tbl.setItem(r, 4, QTableWidgetItem(row.status))
            tbl.setItem(r, 5, QTableWidgetItem(row.note))

    def _export_expenses_csv(self) -> None:
        svc: ExpenseAuditService = self._container.resolve(ExpenseAuditService)
        rows = svc.filter_rows(
            self._expenses_rows,
            needle=self._expenses_search.text(),
            status=self._expenses_status_filter.currentText(),
        )
        payload = svc.export_csv(rows)
        path, _ = QFileDialog.getSaveFileName(self, "Ausgaben CSV speichern", "expenses.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(payload)
        QMessageBox.information(self, "Ausgaben", f"CSV exportiert:\n{path}")
