"""Steuern module — UVA, Clearing, Ausgaben with non-blocking actions."""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
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
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.clearing.service import ClearingRow, PaymentClearingService
from xw_studio.services.expenses.service import ExpenseAuditService, ExpenseRow
from xw_studio.services.finanzonline import (
    OssQuarterResult,
    OssService,
    OssXmlExport,
    UvaService,
    UvaSubmitResult,
    render_data_quality_text,
    render_reconciliation_text,
)
from xw_studio.ui.widgets.data_table import DataTable
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


def _format_euro(value: str) -> str:
    try:
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return value
    formatted = f"{amount:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", " ")


class TaxesView(QWidget):
    """UVA | Clearing | Ausgaben — calls services off the UI thread."""

    _CLEARING_COLUMNS = ["Ref", "Kunde", "Betrag", "Status", "Hinweis"]
    _EXPENSE_COLUMNS = ["Ref", "Lieferant", "Brutto", "Kategorie", "Status", "Hinweis"]

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._uva_preview_worker: BackgroundWorker | None = None
        self._uva_submit_worker: BackgroundWorker | None = None
        self._oss_worker: BackgroundWorker | None = None
        self._clearing_worker: BackgroundWorker | None = None
        self._expenses_worker: BackgroundWorker | None = None
        self._export_worker: BackgroundWorker | None = None
        self._clearing_rows: list[ClearingRow] = []
        self._expenses_rows: list[ExpenseRow] = []
        self._uva_progress_bar: QProgressBar | None = None
        self._uva_progress_label: QLabel | None = None
        self._uva_preview_button: QPushButton | None = None
        self._uva_submit_button: QPushButton | None = None
        self._uva_amount_label: QLabel | None = None
        self._uva_output: QPlainTextEdit | None = None
        self._zm_output: QPlainTextEdit | None = None
        self._uva_progress_text = ""
        self._uva_progress_timer = QTimer(self)
        self._uva_progress_timer.setInterval(250)
        self._uva_progress_timer.timeout.connect(self._tick_uva_progress)
        self._uva_refresh_button: QPushButton | None = None
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
        layout.setSpacing(10)
        info = QPlainTextEdit()
        uva: UvaService = self._container.resolve(UvaService)
        info.setPlainText(uva.describe_capabilities())
        info.setReadOnly(True)
        info.setMaximumHeight(115)
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Jahr:"))
        year = QSpinBox()
        year.setRange(2000, 2100)
        row.addWidget(year)
        row.addWidget(QLabel("Monat:"))
        month = QSpinBox()
        month.setRange(1, 12)
        row.addWidget(month)
        today = date.today()
        previous_year = today.year if today.month > 1 else today.year - 1
        previous_month = today.month - 1 if today.month > 1 else 12
        year.setValue(previous_year)
        month.setValue(previous_month)
        row.addStretch()
        layout.addLayout(row)

        amount_frame = QFrame()
        amount_frame.setObjectName("uvaAmountFrame")
        amount_frame.setStyleSheet(
            "#uvaAmountFrame {"
            "background: #fff7ed;"
            "border: 1px solid #fdba74;"
            "border-radius: 8px;"
            "}"
        )
        amount_layout = QVBoxLayout(amount_frame)
        amount_layout.setContentsMargins(14, 10, 14, 10)
        amount_title = QLabel("Zu zahlender Betrag UVA")
        amount_title.setStyleSheet("color: #9a3412; font-weight: 700;")
        self._uva_amount_label = QLabel("Noch nicht berechnet")
        self._uva_amount_label.setStyleSheet("color: #7c2d12; font-size: 24px; font-weight: 800;")
        amount_layout.addWidget(amount_title)
        amount_layout.addWidget(self._uva_amount_label)
        layout.addWidget(amount_frame)

        result_row = QHBoxLayout()
        result_row.setSpacing(10)

        uva_box = QGroupBox("UVA / U30 Auswertung")
        uva_layout = QVBoxLayout(uva_box)
        self._uva_output = QPlainTextEdit()
        self._uva_output.setReadOnly(True)
        self._uva_output.setPlaceholderText("UVA berechnen, um Kennzahlen und Beträge zu sehen.")
        uva_layout.addWidget(self._uva_output)
        result_row.addWidget(uva_box, 3)

        zm_box = QGroupBox("Zusammenfassende Meldung / U13")
        zm_layout = QVBoxLayout(zm_box)
        self._zm_output = QPlainTextEdit()
        self._zm_output.setReadOnly(True)
        self._zm_output.setPlaceholderText("UVA berechnen, um ZM-Zeilen zu sehen.")
        zm_layout.addWidget(self._zm_output)
        result_row.addWidget(zm_box, 2)
        layout.addLayout(result_row, 1)

        self._uva_progress_label = QLabel("Bereit")
        self._uva_progress_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self._uva_progress_label)

        self._uva_progress_bar = QProgressBar()
        self._uva_progress_bar.setRange(0, 100)
        self._uva_progress_bar.setValue(0)
        self._uva_progress_bar.hide()
        layout.addWidget(self._uva_progress_bar)

        preview = QPushButton("UVA berechnen")
        refresh = QPushButton("Neu aus sevDesk laden")
        submit = QPushButton("UVA + ZM an FinanzOnline senden")
        self._uva_preview_button = preview
        self._uva_refresh_button = refresh
        self._uva_submit_button = submit

        def on_progress(value: int, text: str) -> None:
            self._set_uva_progress(value, text)

        def start_preview(*, refresh_data: bool) -> None:
            if self._uva_preview_worker is not None and self._uva_preview_worker.isRunning():
                return
            if self._uva_submit_worker is not None and self._uva_submit_worker.isRunning():
                return

            self._set_uva_busy(True)
            self._set_uva_progress(5, "UVA-Berechnung wird vorbereitet...")
            selected_year = year.value()
            selected_month = month.value()

            def job() -> dict[str, object]:
                self._emit_uva_preview_progress(20, "UVA-Daten werden aus sevDesk geladen...")
                payload = uva.calculate_month(selected_year, selected_month, refresh=refresh_data)
                self._emit_uva_preview_progress(100, "UVA-Berechnung abgeschlossen")
                return payload

            self._uva_preview_worker = BackgroundWorker(job)

            def on_preview_result(payload: object) -> None:
                if not isinstance(payload, dict):
                    self._set_uva_result_text("Keine gueltige UVA-Antwort erhalten.", "")
                    return
                self._set_uva_payload(payload)

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

        def on_preview() -> None:
            start_preview(refresh_data=False)

        def on_refresh() -> None:
            start_preview(refresh_data=True)

        def on_submit() -> None:
            if self._uva_submit_worker is not None and self._uva_submit_worker.isRunning():
                return
            if self._uva_preview_worker is not None and self._uva_preview_worker.isRunning():
                return

            self._set_uva_busy(True)
            self._set_uva_progress(5, "UVA/U13 wird vorbereitet...")
            selected_year = year.value()
            selected_month = month.value()

            def job() -> UvaSubmitResult:
                self._emit_uva_submit_progress(20, "UVA-Payload wird erstellt...")
                self._emit_uva_submit_progress(45, "UVA wird an FinanzOnline gesendet...")
                result = uva.submit_month(selected_year, selected_month)
                self._emit_uva_submit_progress(100, "Sendevorgang abgeschlossen")
                return result

            self._uva_submit_worker = BackgroundWorker(job)

            def on_uva_result(res: object) -> None:
                if not isinstance(res, UvaSubmitResult):
                    QMessageBox.warning(self, "UVA + ZM", "Keine gueltige Antwort erhalten.")
                    return
                self._show_uva_submit_result(res)

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
        refresh.clicked.connect(on_refresh)
        submit.clicked.connect(on_submit)
        buttons = QHBoxLayout()
        buttons.addWidget(preview)
        buttons.addWidget(refresh)
        buttons.addWidget(submit)
        buttons.addStretch()
        layout.addLayout(buttons)
        return page

    def _set_uva_payload(self, payload: dict[str, object]) -> None:
        zahlbetrag = str(payload.get("zahlbetrag") or "").strip()
        self._set_uva_amount(zahlbetrag)

        preview_text = str(payload.get("preview_text") or "").strip()
        kennzahlen_text = str(payload.get("kennzahlen_text") or "").strip()
        warnings_value = payload.get("warnings")
        warning_lines = [
            str(item)
            for item in warnings_value
            if isinstance(item, str)
        ] if isinstance(warnings_value, list) else []
        grouped_warnings_text = _render_grouped_uva_warnings(warning_lines)
        amount_text = f"ZU ZAHLEN: EUR {_format_euro(zahlbetrag)}" if zahlbetrag else "ZU ZAHLEN: noch nicht ermittelt"
        cache_text = ""
        cache_value = payload.get("cache")
        if isinstance(cache_value, dict):
            source = str(cache_value.get("source") or "").strip()
            elapsed = cache_value.get("elapsed_seconds")
            snapshot_hash = str(cache_value.get("snapshot_hash") or "").strip()
            if cache_value.get("hit"):
                if source == "persistent":
                    cache_text = "Datenstatus: aus persistentem Monats-Snapshot geladen"
                else:
                    cache_text = "Datenstatus: aus Monatscache geladen"
            elif source == "live" and elapsed is not None:
                cache_text = f"Datenstatus: live geladen in {elapsed} s"
            if snapshot_hash:
                cache_text = f"{cache_text}\nSnapshot: {snapshot_hash[:12]}" if cache_text else f"Snapshot: {snapshot_hash[:12]}"
        reconciliation_value = payload.get("reconciliation")
        reconciliation_text = (
            render_reconciliation_text(reconciliation_value)
            if isinstance(reconciliation_value, dict)
            else ""
        )
        data_quality_value = payload.get("data_quality")
        data_quality_text = (
            render_data_quality_text(data_quality_value)
            if isinstance(data_quality_value, dict)
            else ""
        )
        uva_text = "\n\n".join(
            part
            for part in [
                amount_text,
                cache_text,
                data_quality_text,
                kennzahlen_text,
                reconciliation_text,
                preview_text,
                grouped_warnings_text,
            ]
            if part
        )
        zm_text = str(payload.get("zm_text") or "").strip()
        if not zm_text:
            zm_text = "Keine ZM-Auswertung vorhanden oder ZM/U13 ist nicht aktiv."
        self._set_uva_result_text(uva_text or repr(payload), zm_text)

    def _set_uva_amount(self, value: str) -> None:
        if self._uva_amount_label is None:
            return
        if not value:
            self._uva_amount_label.setText("Noch nicht berechnet")
            return
        self._uva_amount_label.setText(f"EUR {_format_euro(value)}")

    def _set_uva_result_text(self, uva_text: str, zm_text: str) -> None:
        if self._uva_output is not None:
            self._uva_output.setPlainText(uva_text)
        if self._zm_output is not None:
            self._zm_output.setPlainText(zm_text)

    def _show_uva_submit_result(self, res: UvaSubmitResult) -> None:
        uva_state = "erfolgreich" if res.ok else "fehlgeschlagen"
        lines = [
            f"U30/UVA: {uva_state}",
            f"Antwort: {res.message or '-'}",
            f"Referenz: {res.reference_id or '-'}",
            f"Modus: {'Testuebermittlung' if res.test_mode else 'Produktivuebermittlung'}",
            f"XML validiert: {'ja' if res.xml_validated else 'nein'}",
        ]
        if res.uva_payload:
            amount = str(res.uva_payload.get("zahlbetrag") or "").strip()
            period = str(res.uva_payload.get("zeitraum") or "").strip()
            if period:
                lines.insert(0, f"Periode: {period}")
            if amount:
                lines.insert(1, f"UVA-Zahlbetrag: EUR {_format_euro(amount)}")

        if res.zm_ok is not None:
            zm_state = "erfolgreich" if res.zm_ok else "fehlgeschlagen"
            lines.extend(
                [
                    "",
                    f"U13/ZM: {zm_state}",
                    f"Antwort: {res.zm_message or '-'}",
                    f"Referenz: {res.zm_reference_id or '-'}",
                    f"ZM-Zeilen: {res.zm_rows}",
                    f"XML validiert: {'ja' if res.zm_xml_validated else 'nein'}",
                ]
            )

        detail_parts = []
        if res.uva_payload:
            detail_parts.append("Gesendeter U30-Payload:\n" + repr(res.uva_payload))
        if res.xml_payload:
            detail_parts.append("Gesendetes U30-XML:\n" + res.xml_payload)
        if res.zm_payload:
            detail_parts.append("Gesendeter U13/ZM-Payload:\n" + repr(res.zm_payload))
        if res.zm_xml_payload:
            detail_parts.append("Gesendetes U13/ZM-XML:\n" + res.zm_xml_payload)

        box = QMessageBox(self)
        box.setWindowTitle("UVA + ZM Abgabe")
        box.setIcon(QMessageBox.Icon.Information if res.ok and (res.zm_ok is not False) else QMessageBox.Icon.Warning)
        box.setText("Sendevorgang abgeschlossen." if res.ok else "Sendevorgang mit Fehler.")
        box.setInformativeText("\n".join(lines))
        if detail_parts:
            box.setDetailedText("\n\n".join(detail_parts))
        box.exec()

    def _set_uva_busy(self, busy: bool) -> None:
        for button in (self._uva_preview_button, self._uva_refresh_button, self._uva_submit_button):
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
            if self._oss_worker is not None and self._oss_worker.isRunning():
                return
            selected_year = year.value()
            selected_quarter_value = selected_quarter()
            preview.setEnabled(False)
            export.setEnabled(False)
            preview.setText("Berechne...")

            def job() -> OssQuarterResult:
                return oss.calculate_quarter(selected_year, selected_quarter_value)

            self._oss_worker = BackgroundWorker(job)

            def on_result(res: object) -> None:
                if not isinstance(res, OssQuarterResult):
                    return
                preview_box.setPlainText(oss.render_preview_text(res))

            self._oss_worker.signals.result.connect(on_result)
            self._oss_worker.signals.error.connect(
                lambda exc: QMessageBox.information(self, "EU-OSS", f"Fehler: {exc}")
            )
            self._oss_worker.signals.finished.connect(on_oss_finished)
            self._oss_worker.start()

        def on_export() -> None:
            if self._oss_worker is not None and self._oss_worker.isRunning():
                return
            current_oss_id = oss_id.text().strip()
            if not current_oss_id:
                QMessageBox.information(self, "EU-OSS", "Bitte zuerst eine OSS-ID eintragen.")
                return

            selected_path, _ = QFileDialog.getSaveFileName(
                self,
                "EU-OSS XML speichern",
                f"oss_{year.value()}_Q{selected_quarter()}.xml",
                "XML (*.xml);;Alle Dateien (*.*)",
            )
            if not selected_path:
                return
            selected_year = year.value()
            selected_quarter_value = selected_quarter()
            selected_uid = uid_fixed_est.text().strip()
            preview.setEnabled(False)
            export.setEnabled(False)
            export.setText("Exportiere...")

            def job() -> tuple[OssXmlExport, str]:
                result = oss.build_xml_export(
                    selected_year,
                    selected_quarter_value,
                    oss_id=current_oss_id,
                    uid_fixed_est=selected_uid,
                )
                Path(selected_path).write_text(result.xml_payload, encoding="utf-8")
                return result, selected_path

            self._oss_worker = BackgroundWorker(job)

            def on_result(payload: object) -> None:
                if not isinstance(payload, tuple) or len(payload) != 2:
                    return
                res, saved_path = payload
                if not isinstance(res, OssXmlExport):
                    return
                preview_box.setPlainText(res.xml_payload)
                QMessageBox.information(
                    self,
                    "EU-OSS",
                    f"XML gespeichert:\n{saved_path}\n\nDanach im EU-OSS-Portal hochladen und pruefen.",
                )

            self._oss_worker.signals.result.connect(on_result)
            self._oss_worker.signals.error.connect(
                lambda exc: QMessageBox.information(self, "EU-OSS", f"Fehler: {exc}")
            )
            self._oss_worker.signals.finished.connect(on_oss_finished)
            self._oss_worker.start()

        def on_oss_finished() -> None:
            self._oss_worker = None
            preview.setEnabled(True)
            preview.setText("EU-OSS berechnen")
            export.setEnabled(True)
            export.setText("EU-OSS XML speichern")

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

        self._clearing_table = DataTable(self._CLEARING_COLUMNS)
        self._clearing_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._clearing_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._clearing_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
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

        self._expenses_table = DataTable(self._EXPENSE_COLUMNS)
        self._expenses_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._expenses_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._expenses_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
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
        payload = [
            {
                "Ref": row.ref,
                "Kunde": row.customer,
                "Betrag": row.amount,
                "Status": row.status,
                "Hinweis": row.note,
                "__align__Betrag": "right",
            }
            for row in rows
        ]
        self._clearing_table.set_data(payload)

    def _export_clearing_csv(self) -> None:
        if self._export_worker is not None and self._export_worker.isRunning():
            return
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

        def job() -> str:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(payload)
            return path

        self._export_worker = BackgroundWorker(job)
        self._export_worker.signals.result.connect(lambda saved_path: QMessageBox.information(self, "Clearing", f"CSV exportiert:\n{saved_path}"))
        self._export_worker.signals.error.connect(lambda exc: QMessageBox.warning(self, "Clearing", f"CSV-Export fehlgeschlagen: {exc}"))
        self._export_worker.signals.finished.connect(lambda: setattr(self, "_export_worker", None))
        self._export_worker.start()

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
        payload = [
            {
                "Ref": row.ref,
                "Lieferant": row.supplier,
                "Brutto": row.gross_amount,
                "Kategorie": row.category,
                "Status": row.status,
                "Hinweis": row.note,
                "__align__Brutto": "right",
            }
            for row in rows
        ]
        self._expenses_table.set_data(payload)

    def _export_expenses_csv(self) -> None:
        if self._export_worker is not None and self._export_worker.isRunning():
            return
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

        def job() -> str:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(payload)
            return path

        self._export_worker = BackgroundWorker(job)
        self._export_worker.signals.result.connect(lambda saved_path: QMessageBox.information(self, "Ausgaben", f"CSV exportiert:\n{saved_path}"))
        self._export_worker.signals.error.connect(lambda exc: QMessageBox.warning(self, "Ausgaben", f"CSV-Export fehlgeschlagen: {exc}"))
        self._export_worker.signals.finished.connect(lambda: setattr(self, "_export_worker", None))
        self._export_worker.start()
