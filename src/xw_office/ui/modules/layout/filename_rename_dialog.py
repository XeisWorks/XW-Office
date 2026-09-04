"""Preview-first batch renaming for legacy MH-AudioPlayer files."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.filename_generator.mh_tracks_cms_import import (
    MhTracksCmsApplyResult,
    MhTracksCmsImportService,
)
from xw_office.services.filename_generator.mh_tracks_import_core import MhTracksImportPlan
from xw_office.services.filename_generator.models import (
    FilenameGeneratorError,
    FilenameRenameOperation,
    FilenameRenameRules,
)
from xw_office.services.filename_generator.service import FilenameGeneratorService
from xw_office.services.filename_generator.wix_media_upload import (
    WixMediaUploadResult,
    WixMediaUploadService,
)

_CMS_ACTION_LABELS = {
    "add-stem": "Neue Spur",
    "replace-audio": "Audio ersetzen",
    "create-track-and-stem": "Neuer Track-Entwurf",
    "unchanged": "Unverändert",
}


@dataclass(frozen=True)
class _RenamePreset:
    label: str
    edition: str
    instrument: str
    markers_override: bool


_PRESETS = (
    _RenamePreset("Starterkit tief – B-Tuba (fest)", "sk-t", "btb", False),
    _RenamePreset("Starterkit hoch – B-Tuba (fest)", "sk-h", "btb", False),
    _RenamePreset("Starterkit – aus Dateinamen erkennen", "", "", True),
    _RenamePreset("Benutzerdefiniert", "", "", False),
)

_VARIANT_MAPPING = "1=practice, 2=teacher"
_EDITION_MAPPING = "tief=sk-t, hoch=sk-h"
_INSTRUMENT_MAPPING = (
    "btb=btb, b-tuba=btb, ftb=ftb, posaune=pos, pos=pos, "
    "trompete=trp, trp=trp, horn=hrn, hrn=hrn"
)


class FilenameRenamePanel(QWidget):
    """Scan, review, edit, and explicitly apply a safe rename plan."""

    COL_SELECT = 0
    COL_SOURCE = 1
    COL_TRACK = 2
    COL_EDITION = 3
    COL_INSTRUMENT = 4
    COL_ROLE = 5
    COL_TARGET = 6
    COL_STATUS = 7

    def __init__(
        self,
        service: FilenameGeneratorService,
        wix_upload_service: WixMediaUploadService | None = None,
        cms_import_service: MhTracksCmsImportService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._wix_upload_service = wix_upload_service
        self._cms_import_service = cms_import_service
        self._upload_worker: BackgroundWorker | None = None
        self._cms_worker: BackgroundWorker | None = None
        self._last_upload: WixMediaUploadResult | None = None
        self._pending_cms_plan: MhTracksImportPlan | None = None
        self._pending_cms_plan_folder: str = ""
        self._last_cms_track_url: str = ""
        self._wix_path_is_suggestion = False
        self._updating_table = False

        root = QVBoxLayout(self)
        intro = QLabel(
            "Der Scan verändert keine Dateien. Nur eindeutig erkannte Zeilen werden vorausgewählt. "
            "Zielnamen können vor der bestätigten Umbenennung bearbeitet werden."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        folder_group = QGroupBox("Quellordner")
        folder_layout = QHBoxLayout(folder_group)
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Ordner mit MP3-Dateien auswählen")
        folder_layout.addWidget(self._folder_edit, stretch=1)
        browse_button = QPushButton("Ordner wählen…")
        browse_button.clicked.connect(self._pick_folder)
        folder_layout.addWidget(browse_button)
        root.addWidget(folder_group)

        rules_group = QGroupBox("Erkennungsregeln")
        rules_form = QFormLayout(rules_group)
        self._preset_combo = QComboBox()
        for preset in _PRESETS:
            self._preset_combo.addItem(preset.label)
        self._preset_combo.currentIndexChanged.connect(self._apply_preset)
        rules_form.addRow("Preset:", self._preset_combo)

        defaults_row = QHBoxLayout()
        self._edition_edit = QLineEdit()
        self._edition_edit.setPlaceholderText("leer = Marker erforderlich")
        defaults_row.addWidget(QLabel("Edition:"))
        defaults_row.addWidget(self._edition_edit)
        self._instrument_edit = QLineEdit()
        self._instrument_edit.setPlaceholderText("leer = Marker erforderlich")
        defaults_row.addWidget(QLabel("Instrument:"))
        defaults_row.addWidget(self._instrument_edit)
        self._track_width = QSpinBox()
        self._track_width.setRange(1, 4)
        self._track_width.setValue(2)
        defaults_row.addWidget(QLabel("Trackbreite:"))
        defaults_row.addWidget(self._track_width)
        rules_form.addRow("Standardwerte:", defaults_row)

        self._variant_mapping_edit = QLineEdit(_VARIANT_MAPPING)
        rules_form.addRow("Varianten (.Nummer):", self._variant_mapping_edit)
        self._edition_mapping_edit = QLineEdit(_EDITION_MAPPING)
        rules_form.addRow("Editionsmarker:", self._edition_mapping_edit)
        self._instrument_mapping_edit = QLineEdit(_INSTRUMENT_MAPPING)
        rules_form.addRow("Instrumentmarker:", self._instrument_mapping_edit)

        options_row = QHBoxLayout()
        self._markers_override_check = QCheckBox("Marker überschreiben Standardwerte")
        self._markers_override_check.setToolTip(
            "Für gemischte Ordner: erkannte Marker haben Vorrang. Bei festen Presets führen "
            "widersprüchliche Marker stattdessen zu einer Warnung."
        )
        options_row.addWidget(self._markers_override_check)
        self._keep_title_check = QCheckBox('Titel als " -- Titel" behalten')
        options_row.addWidget(self._keep_title_check)
        options_row.addStretch()
        rules_form.addRow("Optionen:", options_row)
        root.addWidget(rules_group)

        scan_row = QHBoxLayout()
        self._scan_button = QPushButton("Ordner scannen")
        self._scan_button.clicked.connect(self._scan)
        scan_row.addWidget(self._scan_button)
        select_safe_button = QPushButton("Alle eindeutigen auswählen")
        select_safe_button.clicked.connect(self._select_safe_rows)
        scan_row.addWidget(select_safe_button)
        clear_button = QPushButton("Auswahl aufheben")
        clear_button.clicked.connect(self._clear_selection)
        scan_row.addWidget(clear_button)
        scan_row.addStretch()
        root.addLayout(scan_row)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["✓", "Alter Dateiname", "Track", "Edition", "Instrument", "Rolle", "Neuer Dateiname", "Status"]
        )
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(self.COL_SELECT, QHeaderView.ResizeMode.ResizeToContents)
        for column in (self.COL_TRACK, self.COL_EDITION, self.COL_INSTRUMENT, self.COL_ROLE):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_TARGET, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Stretch)
        self._table.itemChanged.connect(self._update_rename_button)
        self._table.itemChanged.connect(self._apply_manual_cell_change)
        self._table.setMinimumHeight(220)
        root.addWidget(self._table, stretch=1)

        action_row = QHBoxLayout()
        self._status_label = QLabel("Bereit")
        self._status_label.setWordWrap(True)
        action_row.addWidget(self._status_label, stretch=1)
        self._undo_button = QPushButton("Letzte Umbenennung rückgängig")
        self._undo_button.setEnabled(self._service.can_undo_last_rename)
        self._undo_button.clicked.connect(self._undo)
        action_row.addWidget(self._undo_button)
        self._rename_button = QPushButton("Ausgewählte Dateien umbenennen")
        self._rename_button.setEnabled(False)
        self._rename_button.clicked.connect(self._rename_selected)
        action_row.addWidget(self._rename_button)
        root.addLayout(action_row)

        upload_group = QGroupBox("Direkt zu Wix hochladen")
        upload_layout = QVBoxLayout(upload_group)
        upload_path_row = QHBoxLayout()
        self._wix_path_edit = QLineEdit()
        self._wix_path_edit.setPlaceholderText(
            "/MH-Tracks/sk-t/btb/uploads/20260903-143000"
        )
        self._wix_path_edit.textEdited.connect(self._mark_wix_path_as_manual)
        upload_path_row.addWidget(QLabel("Wix-Zielpfad:"))
        upload_path_row.addWidget(self._wix_path_edit, stretch=1)
        upload_layout.addLayout(upload_path_row)

        upload_actions = QHBoxLayout()
        self._upload_button = QPushButton("Alle gültigen MP3s hochladen")
        self._upload_button.setEnabled(bool(wix_upload_service and wix_upload_service.is_configured))
        self._upload_button.clicked.connect(self._start_upload)
        upload_actions.addWidget(self._upload_button)
        upload_actions.addStretch()
        upload_layout.addLayout(upload_actions)

        self._upload_progress = QProgressBar()
        self._upload_progress.setRange(0, 100)
        self._upload_progress.setValue(0)
        upload_layout.addWidget(self._upload_progress)
        self._upload_status = QLabel(
            "Bereit. Hochgeladen werden alle bereits gültig benannten MP3-Dateien im Quellordner."
            if wix_upload_service and wix_upload_service.is_configured
            else "WIX_API_KEY oder WIX_SITE_ID fehlt; direkter Upload ist deaktiviert."
        )
        self._upload_status.setWordWrap(True)
        upload_layout.addWidget(self._upload_status)
        root.addWidget(upload_group)

        cms_group = QGroupBox("MH-Tracks CMS aktualisieren")
        cms_layout = QVBoxLayout(cms_group)
        cms_intro = QLabel(
            "Ersetzt die öffentliche Wix-Importseite. Prüft zuerst nicht-destruktiv, was sich ändern würde; "
            "erst der zweite Klick auf denselben Button speichert."
        )
        cms_intro.setWordWrap(True)
        cms_layout.addWidget(cms_intro)

        self._cms_button = QPushButton("MH-Tracks CMS prüfen")
        self._cms_button.setEnabled(bool(cms_import_service and cms_import_service.is_configured))
        self._cms_button.clicked.connect(self._start_cms_import)
        cms_layout.addWidget(self._cms_button)

        self._cms_status = QLabel(
            "Bereit."
            if cms_import_service and cms_import_service.is_configured
            else "WIX_API_KEY oder WIX_SITE_ID fehlt; CMS-Import ist deaktiviert."
        )
        self._cms_status.setWordWrap(True)
        self._cms_status.setTextFormat(Qt.TextFormat.RichText)
        cms_layout.addWidget(self._cms_status)

        self._cms_open_first_track_button = QPushButton("Ersten aktualisierten Track öffnen")
        self._cms_open_first_track_button.setEnabled(False)
        self._cms_open_first_track_button.clicked.connect(self._open_first_cms_track)
        cms_layout.addWidget(self._cms_open_first_track_button)
        root.addWidget(cms_group)

        self._apply_preset(0)

    def _apply_preset(self, index: int) -> None:
        preset = _PRESETS[index]
        self._edition_edit.setText(preset.edition)
        self._instrument_edit.setText(preset.instrument)
        self._markers_override_check.setChecked(preset.markers_override)
        if index != len(_PRESETS) - 1:
            self._variant_mapping_edit.setText(_VARIANT_MAPPING)
            self._edition_mapping_edit.setText(_EDITION_MAPPING)
            self._instrument_mapping_edit.setText(_INSTRUMENT_MAPPING)

    def _pick_folder(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "MP3-Quellordner auswählen", start)
        if selected:
            self._folder_edit.setText(selected)
            self._scan()

    def _rules(self) -> FilenameRenameRules:
        return FilenameRenameRules(
            default_edition_slug=self._edition_edit.text(),
            default_instrument_slug=self._instrument_edit.text(),
            variant_roles=self._service.parse_mapping(
                self._variant_mapping_edit.text(), field_name="Varianten"
            ),
            edition_markers=self._service.parse_mapping(
                self._edition_mapping_edit.text(), field_name="Editionsmarker"
            ),
            instrument_markers=self._service.parse_mapping(
                self._instrument_mapping_edit.text(), field_name="Instrumentmarker"
            ),
            markers_override_defaults=self._markers_override_check.isChecked(),
            keep_title=self._keep_title_check.isChecked(),
            track_width=self._track_width.value(),
        )

    def _scan(self) -> None:
        try:
            plan = self._service.build_rename_plan(self._folder_edit.text(), self._rules())
        except FilenameGeneratorError as exc:
            QMessageBox.warning(self, "Scan nicht möglich", str(exc))
            return

        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for plan_item in plan:
            row = self._table.rowCount()
            self._table.insertRow(row)
            select_item = QTableWidgetItem()
            select_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
            )
            select_item.setCheckState(
                Qt.CheckState.Checked if plan_item.is_safe else Qt.CheckState.Unchecked
            )
            select_item.setData(Qt.ItemDataRole.UserRole, str(plan_item.source_path))
            select_item.setData(Qt.ItemDataRole.UserRole + 1, plan_item.status)
            select_item.setData(Qt.ItemDataRole.UserRole + 2, plan_item.title)
            self._table.setItem(row, self.COL_SELECT, select_item)
            self._set_read_only_item(row, self.COL_SOURCE, plan_item.source_path.name)
            self._table.setItem(row, self.COL_TRACK, QTableWidgetItem(plan_item.track_number))
            self._table.setItem(row, self.COL_EDITION, QTableWidgetItem(plan_item.edition_slug))
            self._table.setItem(row, self.COL_INSTRUMENT, QTableWidgetItem(plan_item.instrument_slug))
            self._table.setItem(row, self.COL_ROLE, QTableWidgetItem(plan_item.role))
            self._table.setItem(row, self.COL_TARGET, QTableWidgetItem(plan_item.target_name))
            status_text = {
                "ready": "Eindeutig",
                "canonical": "Bereits korrekt",
                "conflict": "Konflikt",
                "review": "Prüfen",
            }.get(plan_item.status, plan_item.status)
            self._set_read_only_item(row, self.COL_STATUS, f"{status_text}: {plan_item.message}")
        self._table.blockSignals(False)

        safe_count = sum(item.is_safe for item in plan)
        review_count = sum(item.status in {"review", "conflict"} for item in plan)
        canonical_count = sum(item.status == "canonical" for item in plan)
        self._status_label.setText(
            f"{len(plan)} MP3-Dateien: {safe_count} eindeutig, {review_count} zu prüfen, "
            f"{canonical_count} bereits korrekt."
        )
        self._suggest_wix_path()
        self._update_rename_button()

    def _set_read_only_item(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, column, item)

    def _select_safe_rows(self) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, self.COL_SELECT)
            if item is not None:
                is_safe = item.data(Qt.ItemDataRole.UserRole + 1) == "ready"
                item.setCheckState(Qt.CheckState.Checked if is_safe else Qt.CheckState.Unchecked)
        self._update_rename_button()

    def _clear_selection(self) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, self.COL_SELECT)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._update_rename_button()

    def _update_rename_button(self, _item: QTableWidgetItem | None = None) -> None:
        has_selected_target = False
        for row in range(self._table.rowCount()):
            select_item = self._table.item(row, self.COL_SELECT)
            target_item = self._table.item(row, self.COL_TARGET)
            if (
                select_item is not None
                and select_item.checkState() == Qt.CheckState.Checked
                and target_item is not None
                and target_item.text().strip()
            ):
                has_selected_target = True
                break
        self._rename_button.setEnabled(has_selected_target)

    def _apply_manual_cell_change(self, item: QTableWidgetItem) -> None:
        """Keep the editable metadata columns and target-name cell in sync."""
        if self._updating_table or item.column() not in {
            self.COL_TRACK,
            self.COL_EDITION,
            self.COL_INSTRUMENT,
            self.COL_ROLE,
            self.COL_TARGET,
        }:
            return
        row = item.row()
        select_item = self._table.item(row, self.COL_SELECT)
        status_item = self._table.item(row, self.COL_STATUS)
        if select_item is None or status_item is None:
            return

        self._updating_table = True
        try:
            if item.column() == self.COL_TARGET:
                status_item.setText("Manuell: Zielname wird vor dem Umbenennen geprüft.")
            else:
                target_name = self._target_from_row(row, select_item)
                target_item = self._table.item(row, self.COL_TARGET)
                if target_item is not None:
                    target_item.setText(target_name)
                status_item.setText("Manuell: Zielname aus bearbeiteten Angaben erzeugt.")
            select_item.setCheckState(Qt.CheckState.Checked)
        finally:
            self._updating_table = False

    def _target_from_row(self, row: int, select_item: QTableWidgetItem) -> str:
        track_item = self._table.item(row, self.COL_TRACK)
        edition_item = self._table.item(row, self.COL_EDITION)
        instrument_item = self._table.item(row, self.COL_INSTRUMENT)
        role_item = self._table.item(row, self.COL_ROLE)
        raw_track = track_item.text().strip() if track_item else ""
        edition = edition_item.text().strip().lower() if edition_item else ""
        instrument = instrument_item.text().strip().lower() if instrument_item else ""
        role = role_item.text().strip().lower() if role_item else ""
        try:
            track = str(int(raw_track)).zfill(self._track_width.value())
        except ValueError:
            return ""
        if not track or not edition or not instrument or not role:
            return ""
        target = f"{edition}__{track}__{instrument}__{role}"
        title = str(select_item.data(Qt.ItemDataRole.UserRole + 2) or "").strip()
        if self._keep_title_check.isChecked() and title:
            target += f" -- {title}"
        return f"{target}.mp3"

    def _selected_operations(self) -> list[FilenameRenameOperation]:
        operations: list[FilenameRenameOperation] = []
        for row in range(self._table.rowCount()):
            select_item = self._table.item(row, self.COL_SELECT)
            target_item = self._table.item(row, self.COL_TARGET)
            if select_item is None or select_item.checkState() != Qt.CheckState.Checked:
                continue
            source_value = select_item.data(Qt.ItemDataRole.UserRole)
            operations.append(
                FilenameRenameOperation(Path(str(source_value)), target_item.text() if target_item else "")
            )
        return operations

    def _rename_selected(self) -> None:
        operations = self._selected_operations()
        if not operations:
            QMessageBox.information(self, "Keine Auswahl", "Bitte mindestens eine Datei auswählen.")
            return
        answer = QMessageBox.question(
            self,
            "Dateien wirklich umbenennen?",
            f"{len(operations)} Datei(en) werden im gewählten Ordner umbenannt. "
            "Vorhandene Dateien werden niemals überschrieben.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._service.execute_rename(self._folder_edit.text(), operations)
        except FilenameGeneratorError as exc:
            QMessageBox.critical(self, "Umbenennung fehlgeschlagen", str(exc))
            return
        self._undo_button.setEnabled(True)
        self._scan()
        self._status_label.setText(
            f"{len(result.operations)} Datei(en) umbenannt. Rückgängig ist in dieser Sitzung möglich."
        )

    def _undo(self) -> None:
        answer = QMessageBox.question(
            self,
            "Letzte Umbenennung rückgängig machen?",
            "Die zuletzt in dieser App-Sitzung umbenannten Dateien erhalten ihre alten Namen zurück.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._service.undo_last_rename()
        except FilenameGeneratorError as exc:
            QMessageBox.critical(self, "Rückgängig fehlgeschlagen", str(exc))
            return
        self._undo_button.setEnabled(False)
        self._scan()
        self._status_label.setText(f"{len(result.operations)} Datei(en) zurückbenannt.")

    def _suggest_wix_path(self) -> None:
        if self._wix_path_edit.text().strip() and not self._wix_path_is_suggestion:
            return
        try:
            files = self._service.canonical_mp3_files(self._folder_edit.text())
        except FilenameGeneratorError:
            return
        if not files:
            return
        identities = {
            (path.name.split("__", 3)[0], path.name.split("__", 3)[2]) for path in files
        }
        if len(identities) == 1:
            edition, instrument = next(iter(identities))
        else:
            edition, instrument = "mixed", "mixed"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._wix_path_edit.setText(
            f"/MH-Tracks/{edition}/{instrument}/uploads/{stamp}"
        )
        self._wix_path_is_suggestion = True

    def _mark_wix_path_as_manual(self, _text: str) -> None:
        self._wix_path_is_suggestion = False

    def _start_upload(self) -> None:
        service = self._wix_upload_service
        if service is None or not service.is_configured:
            QMessageBox.warning(
                self,
                "Wix nicht konfiguriert",
                "Bitte WIX_API_KEY und WIX_SITE_ID in den Einstellungen prüfen.",
            )
            return
        try:
            files = self._service.canonical_mp3_files(self._folder_edit.text())
        except FilenameGeneratorError as exc:
            QMessageBox.warning(self, "Upload nicht möglich", str(exc))
            return
        if not files:
            QMessageBox.information(
                self,
                "Keine Dateien",
                "Im Quellordner wurden keine gültig benannten MH-Tracks-MP3s gefunden.",
            )
            return
        target_path = self._wix_path_edit.text().strip()
        answer = QMessageBox.question(
            self,
            "MP3-Dateien zu Wix hochladen?",
            f"{len(files)} Datei(en) werden in folgenden Wix-Ordner hochgeladen:\n{target_path}\n\n"
            "Bei Namenskonflikten wird nichts überschrieben.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        worker: BackgroundWorker

        def job() -> WixMediaUploadResult:
            return service.upload_files(
                files,
                target_path,
                progress=lambda percent, message: worker.signals.progress.emit(percent, message),
            )

        worker = BackgroundWorker(job)
        self._upload_worker = worker
        worker.signals.progress.connect(self._on_upload_progress)
        worker.signals.result.connect(self._on_upload_result)
        worker.signals.error.connect(self._on_upload_error)
        worker.signals.finished.connect(self._on_upload_finished)
        self._upload_button.setEnabled(False)
        self._upload_progress.setValue(0)
        self._upload_status.setText("Upload wird vorbereitet …")
        worker.start()

    def _on_upload_progress(self, percent: int, message: str) -> None:
        self._upload_progress.setValue(percent)
        self._upload_status.setText(message)

    def _on_upload_result(self, result: object) -> None:
        if not isinstance(result, WixMediaUploadResult):
            return
        self._last_upload = result
        self._upload_progress.setValue(100)
        self._upload_status.setText(
            f"{len(result.files)} Datei(en) hochgeladen. Wix-Ordner: {result.folder.path} "
            f"(ID: {result.folder.folder_id}). "
            + (
                "Bitte nun 'MH-Tracks CMS prüfen' anklicken."
                if result.processing_complete
                else "Wix verarbeitet die Audiodateien noch; die CMS-Prüfung gegebenenfalls nach kurzer Wartezeit wiederholen."
            )
        )

    def _on_upload_error(self, exc: BaseException) -> None:
        self._upload_status.setText(f"Upload fehlgeschlagen: {exc}")
        QMessageBox.critical(self, "Wix-Upload fehlgeschlagen", str(exc))

    def _on_upload_finished(self) -> None:
        self._upload_worker = None
        configured = bool(self._wix_upload_service and self._wix_upload_service.is_configured)
        self._upload_button.setEnabled(configured)

    def _start_cms_import(self) -> None:
        service = self._cms_import_service
        if service is None or not service.is_configured:
            QMessageBox.warning(
                self,
                "Wix nicht konfiguriert",
                "Bitte WIX_API_KEY und WIX_SITE_ID in den Einstellungen prüfen.",
            )
            return
        folder_path = self._wix_path_edit.text().strip()
        if not folder_path:
            QMessageBox.warning(self, "Kein Ordner", "Bitte zuerst einen Wix-Zielpfad angeben.")
            return

        if self._pending_cms_plan is not None and self._pending_cms_plan_folder == folder_path:
            self._confirm_and_apply_cms_import(folder_path, self._pending_cms_plan.token)
            return

        worker: BackgroundWorker = BackgroundWorker(lambda: service.preview(folder_path))
        self._cms_worker = worker
        worker.signals.result.connect(lambda plan: self._on_cms_preview_result(folder_path, plan))
        worker.signals.error.connect(self._on_cms_error)
        worker.signals.finished.connect(self._on_cms_finished)
        self._cms_button.setEnabled(False)
        self._cms_open_first_track_button.setEnabled(False)
        self._cms_status.setText("Vorschau wird geladen …")
        worker.start()

    def _on_cms_preview_result(self, folder_path: str, plan: object) -> None:
        if not isinstance(plan, MhTracksImportPlan):
            return
        self._pending_cms_plan = plan
        self._pending_cms_plan_folder = folder_path
        summary = plan.summary
        lines = [
            f"Erkannte Dateien: {summary.get('recognizedFiles', 0)}",
            f"Zu ändernde Dateien: {summary.get('changedFiles', 0)}",
            f"Neue Track-Entwürfe: {summary.get('inserts', 0)}",
            f"Zu aktualisierende Tracks: {summary.get('updates', 0)}",
            f"Unverändert: {summary.get('unchangedFiles', 0)}",
            f"Ignorierte Dateien: {summary.get('ignoredFiles', 0)}",
            f"Fehler: {summary.get('errors', 0)}",
        ]
        action_lines = [
            f"{_CMS_ACTION_LABELS.get(action.get('type'), action.get('type'))}: "
            f"{action.get('trackKey')} / {action.get('group')}-{action.get('role')} "
            f"← {action.get('fileName')}"
            for action in plan.actions
        ]
        if action_lines:
            lines.append("<b>Geplante Zuordnungen (bitte prüfen):</b>")
            lines.append(self._format_html_list(action_lines))
        if plan.ignored_files:
            lines.append("<b>Ignorierte Dateien (Namensschema nicht erkannt):</b>")
            lines.append(self._format_html_list(plan.ignored_files))
        if plan.errors:
            lines.append("<b>Fehler:</b> " + " | ".join(plan.errors))
        if plan.warnings:
            lines.append("<b>Warnungen:</b> " + " | ".join(plan.warnings[:10]))
        if plan.can_apply:
            lines.append("Noch wurde nichts gespeichert. Prüfen und Button erneut klicken, um zu speichern.")
            self._cms_button.setText("CMS-Vorschau bestätigen")
        else:
            lines.append("Es gibt nichts zu speichern oder Fehler müssen zuerst behoben werden.")
            self._cms_button.setText("MH-Tracks CMS erneut prüfen")
            self._pending_cms_plan = None
        self._cms_status.setText("<br>".join(lines))

    @staticmethod
    def _format_html_list(values: list[str], limit: int = 30) -> str:
        shown = values[:limit]
        items = "".join(f"<li>{item}</li>" for item in shown)
        remainder = len(values) - len(shown)
        tail = f"<li>… und {remainder} weitere</li>" if remainder > 0 else ""
        return f"<ul style='margin:4px 0 4px 18px'>{items}{tail}</ul>"

    def _confirm_and_apply_cms_import(self, folder_path: str, token: str) -> None:
        service = self._cms_import_service
        if service is None:
            return
        answer = QMessageBox.question(
            self,
            "MH-Tracks CMS wirklich aktualisieren?",
            "Die geprüften Änderungen werden jetzt in MH-Tracks/MH-Editions geschrieben.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        worker: BackgroundWorker = BackgroundWorker(lambda: service.apply(folder_path, token))
        self._cms_worker = worker
        worker.signals.result.connect(self._on_cms_apply_result)
        worker.signals.error.connect(self._on_cms_error)
        worker.signals.finished.connect(self._on_cms_finished)
        self._cms_button.setEnabled(False)
        self._cms_status.setText("CMS wird aktualisiert …")
        worker.start()

    def _on_cms_apply_result(self, result: object) -> None:
        if not isinstance(result, MhTracksCmsApplyResult):
            return
        self._pending_cms_plan = None
        self._pending_cms_plan_folder = ""
        self._cms_button.setText("MH-Tracks CMS prüfen")
        lines = [
            f"Neu angelegte Track-Entwürfe: {result.inserted}",
            f"Aktualisierte Tracks: {result.updated}",
        ]
        if result.failures:
            lines.append(
                "<b>Fehlgeschlagen:</b> "
                + " | ".join(f"{failure.track_key}: {failure.message}" for failure in result.failures)
            )
        else:
            lines.append("Alle Änderungen wurden gespeichert.")
        self._cms_status.setText("<br>".join(lines))
        self._last_cms_track_url = result.first_track_url if result.applied else ""
        self._cms_open_first_track_button.setEnabled(bool(self._last_cms_track_url))

    def _open_first_cms_track(self) -> None:
        if not self._last_cms_track_url:
            return
        if not QDesktopServices.openUrl(QUrl(self._last_cms_track_url)):
            QMessageBox.warning(self, "Browser", "Der Track-Link konnte nicht geöffnet werden.")

    def _on_cms_error(self, exc: BaseException) -> None:
        self._cms_status.setText(f"CMS-Import fehlgeschlagen: {exc}")
        QMessageBox.critical(self, "MH-Tracks CMS-Import fehlgeschlagen", str(exc))

    def _on_cms_finished(self) -> None:
        self._cms_worker = None
        configured = bool(self._cms_import_service and self._cms_import_service.is_configured)
        self._cms_button.setEnabled(configured)

