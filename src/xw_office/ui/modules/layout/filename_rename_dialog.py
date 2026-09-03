"""Preview-first batch renaming for legacy MH-AudioPlayer files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.services.filename_generator.models import (
    FilenameGeneratorError,
    FilenameRenameOperation,
    FilenameRenameRules,
)
from xw_office.services.filename_generator.service import FilenameGeneratorService


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


class FilenameRenameDialog(QDialog):
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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle("Audiodateien für MH-Tracks umbenennen")
        self.resize(1220, 720)

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
        close_button = QPushButton("Schließen")
        close_button.clicked.connect(self.accept)
        action_row.addWidget(close_button)
        root.addLayout(action_row)

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
            self._table.setItem(row, self.COL_SELECT, select_item)
            self._set_read_only_item(row, self.COL_SOURCE, plan_item.source_path.name)
            self._set_read_only_item(row, self.COL_TRACK, plan_item.track_number)
            self._set_read_only_item(row, self.COL_EDITION, plan_item.edition_slug)
            self._set_read_only_item(row, self.COL_INSTRUMENT, plan_item.instrument_slug)
            self._set_read_only_item(row, self.COL_ROLE, plan_item.role)
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
