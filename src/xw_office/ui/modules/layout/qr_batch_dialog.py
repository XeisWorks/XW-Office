"""Batch QR-code series generator dialog (variant selection, live preview, progress)."""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.qr_codes.models import (
    GesamtspielchenRow,
    NumericSequenceSpec,
    QrBatchRequest,
    QrBatchSummary,
    QrModuleError,
    QrRecord,
    QrRenderSettings,
    QrVariantPreset,
)
from xw_office.services.qr_codes.presets import (
    GERADE_ZAHLEN_EXCEL,
    GESAMTSPIELCHEN,
    INSTRUMENT_SUGGESTIONS,
    JEDE_4_ZAHL,
    UNGERADE_ZAHLEN_EXCEL,
    WHOLE_SCALE,
    GESAMTSPIELCHEN_DEFAULT_ROWS,
    NumericQrFormData,
    build_numeric_records,
    build_table_records,
    default_numeric_form,
    get_preset,
)
from xw_office.services.qr_codes.service import QrCodeService
from xw_office.ui.dialogs.progress_dialog import ProgressDialog
from xw_office.ui.modules.layout.qr_settings_dialog import QrSettingsDialog
from xw_office.ui.widgets.data_table import DataTable

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)

_VARIANT_ORDER = (WHOLE_SCALE, GESAMTSPIELCHEN, UNGERADE_ZAHLEN_EXCEL, GERADE_ZAHLEN_EXCEL, JEDE_4_ZAHL)
_PREVIEW_COLUMNS = ["Nr.", "Nummer", "ID", "URL", "Dateiname", "Status"]
_PREVIEW_URL_COLUMN = _PREVIEW_COLUMNS.index("URL")
_PREVIEW_DEBOUNCE_MS = 200


class QrCodeBatchDialog(QDialog):
    """"QR-Code-Serie erzeugen..." — variant picker, live preview, batch worker."""

    def __init__(self, container: "Container", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: QrCodeService = container.resolve(QrCodeService)
        self._settings: QrRenderSettings = self._service.load_settings()
        self._current_preset: QrVariantPreset = get_preset(WHOLE_SCALE)
        self._numeric_form: NumericQrFormData | None = None
        self._current_records: tuple[QrRecord, ...] = ()
        self._worker: BackgroundWorker | None = None
        self._progress_dialog: ProgressDialog | None = None

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self.setWindowTitle("QR-Code-Serie erzeugen")
        self.resize(1050, 720)
        self._build_ui()
        self._variant_combo.setCurrentIndex(0)
        self._on_variant_changed()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("Variante:"))
        self._variant_combo = QComboBox()
        for key in _VARIANT_ORDER:
            preset = get_preset(key)
            self._variant_combo.addItem(preset.display_name, preset.key)
        self._variant_combo.currentIndexChanged.connect(self._on_variant_changed)
        header.addWidget(self._variant_combo)
        header.addStretch()
        settings_btn = QPushButton("Globale Einstellungen...")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)
        root.addLayout(header)

        self._legacy_note_label = QLabel("")
        self._legacy_note_label.setWordWrap(True)
        self._legacy_note_label.setStyleSheet("color: #b06a00;")
        root.addWidget(self._legacy_note_label)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_numeric_page())
        self._stack.addWidget(self._build_table_page())
        root.addWidget(self._stack)

        output_group = QGroupBox("Ausgabe")
        output_form = QFormLayout(output_group)

        output_row = QHBoxLayout()
        self._output_dir_edit = QLineEdit(self._settings.last_output_directory)
        self._output_dir_edit.setPlaceholderText("Ausgabeordner wählen...")
        self._output_dir_edit.textChanged.connect(self._schedule_preview_refresh)
        output_row.addWidget(self._output_dir_edit)
        pick_dir_btn = QPushButton("Wählen...")
        pick_dir_btn.clicked.connect(self._pick_output_dir)
        output_row.addWidget(pick_dir_btn)
        output_form.addRow("Ausgabeordner:", output_row)

        self._collision_combo = QComboBox()
        self._collision_combo.addItem("Abbrechen und nichts erzeugen", "abort")
        self._collision_combo.addItem("Vorhandene Dateien überschreiben", "overwrite")
        self._collision_combo.addItem("Automatisch neue Dateinamen vergeben", "rename")
        index = self._collision_combo.findData(self._settings.collision_policy)
        self._collision_combo.setCurrentIndex(max(0, index))
        self._collision_combo.currentIndexChanged.connect(self._schedule_preview_refresh)
        output_form.addRow("Bei vorhandenen Dateien:", self._collision_combo)
        root.addWidget(output_group)

        preview_group = QGroupBox("Vorschau")
        preview_layout = QVBoxLayout(preview_group)
        self._preview_table = DataTable(_PREVIEW_COLUMNS)
        self._preview_table.setMinimumHeight(220)
        self._preview_table.setMouseTracking(True)
        self._preview_table.entered.connect(self._on_preview_table_hovered)
        self._preview_table.clicked.connect(self._on_preview_table_clicked)
        preview_layout.addWidget(self._preview_table)
        root.addWidget(preview_group, stretch=1)

        footer = QHBoxLayout()
        self._count_label = QLabel("")
        self._count_label.setWordWrap(True)
        footer.addWidget(self._count_label, stretch=1)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)
        self._generate_btn = QPushButton("QR-Codes erzeugen")
        self._generate_btn.setEnabled(False)
        self._generate_btn.clicked.connect(self._on_generate_clicked)
        footer.addWidget(self._generate_btn)
        root.addLayout(footer)

    def _build_numeric_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._series_code_edit = QLineEdit()
        self._series_code_edit.textChanged.connect(self._schedule_preview_refresh)
        form.addRow("Kürzel:", self._series_code_edit)

        self._project_slug_edit = QLineEdit()
        self._project_slug_edit.textChanged.connect(self._schedule_preview_refresh)
        form.addRow("URL-Projekt-Slug:", self._project_slug_edit)

        self._instrument_combo = QComboBox()
        self._instrument_combo.setEditable(True)
        self._instrument_combo.addItems(INSTRUMENT_SUGGESTIONS)
        self._instrument_combo.currentTextChanged.connect(self._schedule_preview_refresh)
        form.addRow("Instrument:", self._instrument_combo)

        self._domain_edit = QLineEdit()
        self._domain_edit.textChanged.connect(self._schedule_preview_refresh)
        form.addRow("Domain:", self._domain_edit)

        self._path_template_edit = QLineEdit()
        self._path_template_edit.textChanged.connect(self._schedule_preview_refresh)
        form.addRow("Pfad-/Query-Vorlage:", self._path_template_edit)

        sequence_row = QHBoxLayout()
        self._start_spin = QSpinBox()
        self._start_spin.setRange(0, 100_000)
        self._start_spin.valueChanged.connect(self._schedule_preview_refresh)
        sequence_row.addWidget(QLabel("Start:"))
        sequence_row.addWidget(self._start_spin)

        self._end_spin = QSpinBox()
        self._end_spin.setRange(0, 100_000)
        self._end_spin.valueChanged.connect(self._schedule_preview_refresh)
        sequence_row.addWidget(QLabel("Ende:"))
        sequence_row.addWidget(self._end_spin)

        self._step_spin = QSpinBox()
        self._step_spin.setRange(1, 100_000)
        self._step_spin.valueChanged.connect(self._schedule_preview_refresh)
        sequence_row.addWidget(QLabel("Schritt:"))
        sequence_row.addWidget(self._step_spin)

        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 8)
        self._width_spin.valueChanged.connect(self._schedule_preview_refresh)
        sequence_row.addWidget(QLabel("Mindestbreite:"))
        sequence_row.addWidget(self._width_spin)
        form.addRow("Start / Ende / Schritt / Breite:", sequence_row)

        self._id_template_edit = QLineEdit()
        self._id_template_edit.textChanged.connect(self._schedule_preview_refresh)
        form.addRow("ID-Muster:", self._id_template_edit)

        self._id_suffix_edit = QLineEdit()
        self._id_suffix_edit.textChanged.connect(self._schedule_preview_refresh)
        form.addRow("ID-Suffix:", self._id_suffix_edit)

        return page

    def _build_table_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._table_widget = QTableWidget(0, 3)
        self._table_widget.setHorizontalHeaderLabels(["Nr.", "Anzeigename", "URL-Slug"])
        self._table_widget.verticalHeader().setVisible(False)
        self._table_widget.horizontalHeader().setStretchLastSection(True)
        self._table_widget.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self._table_widget)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Zeile hinzufügen")
        add_btn.clicked.connect(self._add_table_row)
        buttons.addWidget(add_btn)
        remove_btn = QPushButton("Zeile löschen")
        remove_btn.clicked.connect(self._remove_selected_table_row)
        buttons.addWidget(remove_btn)
        reset_btn = QPushButton("Excel-Standard wiederherstellen")
        reset_btn.clicked.connect(lambda: self._load_table_rows(GESAMTSPIELCHEN_DEFAULT_ROWS))
        buttons.addWidget(reset_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        return page

    # ------------------------------------------------------------------
    # Variant switching
    # ------------------------------------------------------------------

    def _on_variant_changed(self) -> None:
        key = self._variant_combo.currentData()
        self._current_preset = get_preset(key)
        self._legacy_note_label.setText(self._current_preset.legacy_note)
        self._legacy_note_label.setVisible(bool(self._current_preset.legacy_note))

        if self._current_preset.generation_mode == "numeric":
            self._numeric_form = default_numeric_form(self._current_preset)
            self._populate_numeric_form(self._numeric_form)
            self._stack.setCurrentIndex(0)
        else:
            self._load_table_rows(GESAMTSPIELCHEN_DEFAULT_ROWS)
            self._stack.setCurrentIndex(1)
        self._schedule_preview_refresh()

    def _populate_numeric_form(self, form: NumericQrFormData) -> None:
        for widget in (
            self._series_code_edit,
            self._project_slug_edit,
            self._domain_edit,
            self._path_template_edit,
            self._id_template_edit,
            self._id_suffix_edit,
        ):
            widget.blockSignals(True)
        self._instrument_combo.blockSignals(True)
        self._start_spin.blockSignals(True)
        self._end_spin.blockSignals(True)
        self._step_spin.blockSignals(True)
        self._width_spin.blockSignals(True)

        self._series_code_edit.setText(form.series_code)
        self._project_slug_edit.setText(form.project_slug)
        self._instrument_combo.setCurrentText(form.instrument_slug)
        self._domain_edit.setText(form.base_domain)
        self._path_template_edit.setText(form.base_path_template)
        self._id_template_edit.setText(form.id_template)
        self._id_suffix_edit.setText(form.id_suffix)
        self._start_spin.setValue(form.sequence.start)
        self._end_spin.setValue(form.sequence.end)
        self._step_spin.setValue(form.sequence.step)
        self._width_spin.setValue(form.sequence.minimum_width)

        for widget in (
            self._series_code_edit,
            self._project_slug_edit,
            self._domain_edit,
            self._path_template_edit,
            self._id_template_edit,
            self._id_suffix_edit,
        ):
            widget.blockSignals(False)
        self._instrument_combo.blockSignals(False)
        self._start_spin.blockSignals(False)
        self._end_spin.blockSignals(False)
        self._step_spin.blockSignals(False)
        self._width_spin.blockSignals(False)

    def _sync_numeric_form_from_widgets(self) -> None:
        if self._numeric_form is None:
            return
        self._numeric_form.series_code = self._series_code_edit.text().strip()
        self._numeric_form.project_slug = self._project_slug_edit.text().strip()
        self._numeric_form.instrument_slug = self._instrument_combo.currentText().strip()
        self._numeric_form.base_domain = self._domain_edit.text().strip()
        self._numeric_form.base_path_template = self._path_template_edit.text()
        self._numeric_form.id_template = self._id_template_edit.text()
        self._numeric_form.id_suffix = self._id_suffix_edit.text()
        self._numeric_form.sequence = NumericSequenceSpec(
            start=self._start_spin.value(),
            end=self._end_spin.value(),
            step=self._step_spin.value(),
            minimum_width=self._width_spin.value(),
            number_suffix=self._numeric_form.sequence.number_suffix,
        )

    # ------------------------------------------------------------------
    # Gesamtspielchen table editing
    # ------------------------------------------------------------------

    def _load_table_rows(self, rows: tuple[GesamtspielchenRow, ...]) -> None:
        self._table_widget.blockSignals(True)
        self._table_widget.setRowCount(len(rows))
        for i, row in enumerate(rows):
            nr_item = QTableWidgetItem(str(i + 1))
            nr_item.setFlags(nr_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table_widget.setItem(i, 0, nr_item)
            self._table_widget.setItem(i, 1, QTableWidgetItem(row.display_name))
            self._table_widget.setItem(i, 2, QTableWidgetItem(row.slug))
        self._table_widget.blockSignals(False)
        self._schedule_preview_refresh()

    def _on_table_item_changed(self, _item: QTableWidgetItem) -> None:
        self._schedule_preview_refresh()

    def _add_table_row(self) -> None:
        row = self._table_widget.rowCount()
        self._table_widget.blockSignals(True)
        self._table_widget.insertRow(row)
        nr_item = QTableWidgetItem(str(row + 1))
        nr_item.setFlags(nr_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table_widget.setItem(row, 0, nr_item)
        self._table_widget.setItem(row, 1, QTableWidgetItem(""))
        self._table_widget.setItem(row, 2, QTableWidgetItem(""))
        self._table_widget.blockSignals(False)
        self._schedule_preview_refresh()

    def _remove_selected_table_row(self) -> None:
        rows = sorted({idx.row() for idx in self._table_widget.selectedIndexes()}, reverse=True)
        if not rows:
            return
        self._table_widget.blockSignals(True)
        for row in rows:
            self._table_widget.removeRow(row)
        for i in range(self._table_widget.rowCount()):
            item = self._table_widget.item(i, 0)
            if item is None:
                item = QTableWidgetItem()
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table_widget.setItem(i, 0, item)
            item.setText(str(i + 1))
        self._table_widget.blockSignals(False)
        self._schedule_preview_refresh()

    def _current_table_rows(self) -> tuple[GesamtspielchenRow, ...]:
        rows: list[GesamtspielchenRow] = []
        for i in range(self._table_widget.rowCount()):
            name_item = self._table_widget.item(i, 1)
            slug_item = self._table_widget.item(i, 2)
            rows.append(
                GesamtspielchenRow(
                    ordinal=i + 1,
                    display_name=name_item.text().strip() if name_item else "",
                    slug=slug_item.text().strip() if slug_item else "",
                )
            )
        return tuple(rows)

    # ------------------------------------------------------------------
    # Live preview
    # ------------------------------------------------------------------

    def _schedule_preview_refresh(self, *_args: object) -> None:
        self._preview_timer.start()

    def _build_current_records(self) -> tuple[QrRecord, ...]:
        if self._current_preset.generation_mode == "numeric":
            self._sync_numeric_form_from_widgets()
            assert self._numeric_form is not None
            return build_numeric_records(self._current_preset, self._numeric_form)
        rows = self._current_table_rows()
        return build_table_records(self._current_preset, rows)

    def _refresh_preview(self) -> None:
        try:
            records = self._build_current_records()
        except QrModuleError as exc:
            self._preview_table.set_data([])
            self._current_records = ()
            self._count_label.setText(str(exc))
            self._generate_btn.setEnabled(False)
            return

        output_dir_text = self._output_dir_edit.text().strip()
        has_blocking_warning = False
        if output_dir_text:
            output_dir = Path(output_dir_text)
            records = self._service.precheck_records(records, output_dir)
            collision_policy = self._collision_combo.currentData()
            has_blocking_warning = collision_policy == "abort" and any(r.warning for r in records)

        self._current_records = records
        rows = []
        for record in records:
            row: dict[str, object] = {
                "Nr.": str(record.ordinal),
                "Nummer": record.source_key,
                "ID": record.logical_id,
                "URL": record.payload_url,
                "Dateiname": record.output_filename,
                "Status": record.warning or "OK",
                "__fg__URL": "#1a5fb4",
                "__tooltip__URL": f"Klicken, um im Standardbrowser zu öffnen:\n{record.payload_url}",
            }
            if record.warning:
                row["__fg__Status"] = "#c0392b"
                row["__tooltip__Status"] = record.warning
            rows.append(row)
        self._preview_table.set_data(rows)

        count_text = f"{len(records)} QR-Code{'s' if len(records) != 1 else ''} werden erzeugt."
        if has_blocking_warning:
            count_text += " Achtung: Kollisionen vorhanden (Regel 'Abbrechen') - Erzeugen ist deaktiviert."
        self._count_label.setText(count_text)
        self._generate_btn.setEnabled(bool(records) and bool(output_dir_text) and not has_blocking_warning)

    def _on_preview_table_hovered(self, index: QModelIndex) -> None:
        is_url_cell = index.isValid() and index.column() == _PREVIEW_URL_COLUMN
        cursor = Qt.CursorShape.PointingHandCursor if is_url_cell else Qt.CursorShape.ArrowCursor
        self._preview_table.viewport().setCursor(cursor)

    def _on_preview_table_clicked(self, index: QModelIndex) -> None:
        if not index.isValid() or index.column() != _PREVIEW_URL_COLUMN:
            return
        url_text = str(index.data(Qt.ItemDataRole.DisplayRole) or "").strip()
        if url_text:
            QDesktopServices.openUrl(QUrl(url_text))

    # ------------------------------------------------------------------
    # Output directory / settings
    # ------------------------------------------------------------------

    def _pick_output_dir(self) -> None:
        start_dir = self._output_dir_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen", start_dir)
        if path:
            self._output_dir_edit.setText(path)

    def _open_settings(self) -> None:
        dialog = QrSettingsDialog(self._service, self._settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._settings = dialog.result_settings()
            self._schedule_preview_refresh()

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _resolve_render_settings_for_run(self) -> QrRenderSettings | None:
        settings = self._settings
        if not settings.logo_enabled or Path(settings.logo_path).is_file():
            return settings

        box = QMessageBox(self)
        box.setWindowTitle("Logo fehlt")
        box.setText(f"Das Standardlogo wurde nicht gefunden:\n{settings.logo_path}\n\nWie möchten Sie fortfahren?")
        pick_btn = box.addButton("Logo auswählen...", QMessageBox.ButtonRole.ActionRole)
        without_btn = box.addButton("Ohne Logo erzeugen", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()

        if clicked == pick_btn:
            path, _ = QFileDialog.getOpenFileName(self, "Logo wählen", "", "Bilder (*.png *.jpg *.jpeg *.webp)")
            if not path:
                return None
            updated = replace(settings, logo_path=path)
            self._settings = updated
            self._service.save_settings(updated)
            return updated
        if clicked == without_btn:
            return replace(settings, logo_enabled=False)
        return None

    def _on_generate_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        output_dir_text = self._output_dir_edit.text().strip()
        if not output_dir_text:
            QMessageBox.warning(self, "QR-Code-Serie", "Bitte zuerst einen Ausgabeordner wählen.")
            return
        try:
            records = self._build_current_records()
        except QrModuleError as exc:
            QMessageBox.warning(self, "QR-Code-Serie", str(exc))
            return
        if not records:
            return

        render_settings = self._resolve_render_settings_for_run()
        if render_settings is None:
            return

        collision_policy = self._collision_combo.currentData()
        request = QrBatchRequest(
            variant_key=self._current_preset.key,
            records=records,
            output_directory=Path(output_dir_text),
            render_settings=render_settings,
            collision_policy=collision_policy,
        )

        self._progress_dialog = ProgressDialog("QR-Codes werden erzeugt...", self)
        self._progress_dialog.rejected.connect(self._cancel_generation)

        def job() -> QrBatchSummary:
            return self._service.generate_batch(
                request,
                progress=self._emit_worker_progress,
                should_cancel=self._should_cancel,
            )

        self._generate_btn.setEnabled(False)
        self._worker = BackgroundWorker(job)
        self._worker.signals.progress.connect(self._on_worker_progress)
        self._worker.signals.result.connect(self._on_batch_done)
        self._worker.signals.error.connect(self._on_batch_error)
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.start()
        self._progress_dialog.show()

    def _emit_worker_progress(self, current: int, total: int, logical_id: str) -> None:
        worker = self._worker
        if worker is None:
            return
        percent = int(current * 100 / total) if total else 0
        worker.signals.progress.emit(percent, f"{current} von {total}: {logical_id}")

    def _should_cancel(self) -> bool:
        worker = self._worker
        return worker is not None and worker.cancelled

    def _cancel_generation(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_worker_progress(self, value: int, text: str) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.set_progress(value, text)

    def _close_progress_dialog(self) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None

    def _on_batch_done(self, data: object) -> None:
        if not isinstance(data, QrBatchSummary):
            return
        self._settings = replace(self._settings, last_output_directory=str(data.output_directory))
        self._service.save_settings(self._settings)
        self._close_progress_dialog()

        lines = [f"Erfolgreich: {data.succeeded}", f"Fehlgeschlagen: {data.failed}"]
        if data.cancelled:
            lines.append("Abgebrochen durch Benutzer - Teilergebnis oben.")
        lines.append(f"\nOrdner:\n{data.output_directory}")
        if data.failed:
            failed_ids = ", ".join(r.record.logical_id for r in data.results if not r.success)
            lines.append(f"\nFehlgeschlagen: {failed_ids}")

        box = QMessageBox(self)
        box.setWindowTitle("Abgebrochen" if data.cancelled else "QR-Codes erzeugt")
        box.setText("\n".join(lines))
        open_btn = box.addButton("Ordner öffnen", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() == open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(data.output_directory)))

    def _on_batch_error(self, exc: BaseException) -> None:
        logger.exception("QR-Batch-Erzeugung fehlgeschlagen: %s", exc)
        self._close_progress_dialog()
        QMessageBox.critical(self, "Fehler", str(exc))

    def _on_worker_finished(self) -> None:
        self._generate_btn.setEnabled(bool(self._current_records))
        self._worker = None
