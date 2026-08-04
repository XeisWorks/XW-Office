"""Global QR-code render settings dialog (size, logo, border, verification)."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from xw_office.services.qr_codes.models import QrModuleError, QrRenderSettings
from xw_office.services.qr_codes.service import QrCodeService

_PREVIEW_EXAMPLE_URL = "https://www.xeisworks.at"
_PREVIEW_DEBOUNCE_MS = 250


class QrSettingsDialog(QDialog):
    """Edit and persist the global QR graphics settings (SettingKvRepository-backed)."""

    def __init__(
        self,
        service: QrCodeService,
        settings: QrRenderSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._result_settings = settings
        self.setWindowTitle("QR-Code-Einstellungen")
        self.setMinimumWidth(480)

        self._qr_preview_timer = QTimer(self)
        self._qr_preview_timer.setSingleShot(True)
        self._qr_preview_timer.setInterval(_PREVIEW_DEBOUNCE_MS)
        self._qr_preview_timer.timeout.connect(self._refresh_qr_preview)

        self._build_ui(settings)
        self._refresh_qr_preview()

    def _build_ui(self, settings: QrRenderSettings) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()

        self._width_spin = QSpinBox()
        self._width_spin.setRange(200, 4000)
        self._width_spin.setValue(settings.width_px)
        self._width_spin.valueChanged.connect(self._schedule_qr_preview_refresh)
        form.addRow("Breite (Pixel):", self._width_spin)

        self._height_spin = QSpinBox()
        self._height_spin.setRange(200, 4000)
        self._height_spin.setValue(settings.height_px)
        self._height_spin.valueChanged.connect(self._schedule_qr_preview_refresh)
        form.addRow("Höhe (Pixel):", self._height_spin)

        form.addRow("Ausgabeformat:", QLabel("PNG"))
        form.addRow("Fehlerkorrektur:", QLabel("H (fest)"))

        self._border_spin = QSpinBox()
        self._border_spin.setRange(0, 20)
        self._border_spin.setValue(settings.border_modules)
        self._border_spin.valueChanged.connect(self._schedule_qr_preview_refresh)
        form.addRow("Rand (Module):", self._border_spin)

        self._logo_checkbox = QCheckBox("Mittellogo verwenden")
        self._logo_checkbox.setChecked(settings.logo_enabled)
        self._logo_checkbox.toggled.connect(self._schedule_qr_preview_refresh)
        form.addRow(self._logo_checkbox)

        logo_row = QHBoxLayout()
        self._logo_path_edit = QLineEdit(settings.logo_path)
        logo_row.addWidget(self._logo_path_edit)
        pick_logo_btn = QPushButton("Datei wählen...")
        pick_logo_btn.clicked.connect(self._pick_logo)
        logo_row.addWidget(pick_logo_btn)
        form.addRow("Logo-Pfad:", logo_row)

        self._logo_preview = QLabel("(keine Vorschau)")
        self._logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo_preview.setFixedSize(96, 96)
        form.addRow("Vorschau:", self._logo_preview)
        self._refresh_logo_preview(settings.logo_path)
        self._logo_path_edit.textChanged.connect(self._refresh_logo_preview)
        self._logo_path_edit.textChanged.connect(self._schedule_qr_preview_refresh)

        self._logo_max_width_spin = QDoubleSpinBox()
        self._logo_max_width_spin.setRange(1.0, 40.0)
        self._logo_max_width_spin.setSuffix(" %")
        self._logo_max_width_spin.setValue(settings.logo_max_width_percent)
        self._logo_max_width_spin.valueChanged.connect(self._schedule_qr_preview_refresh)
        form.addRow("Logo-Breite (Anteil des Symbols):", self._logo_max_width_spin)

        self._logo_backplate_spin = QDoubleSpinBox()
        self._logo_backplate_spin.setRange(1.0, 40.0)
        self._logo_backplate_spin.setSuffix(" %")
        self._logo_backplate_spin.setValue(settings.logo_backplate_width_percent)
        self._logo_backplate_spin.valueChanged.connect(self._schedule_qr_preview_refresh)
        form.addRow("Weiße Hintergrundfläche:", self._logo_backplate_spin)

        self._qr_preview_label = QLabel("(wird berechnet...)")
        self._qr_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_preview_label.setFixedSize(200, 200)
        qr_preview_caption = QLabel()
        qr_preview_caption.setTextFormat(Qt.TextFormat.RichText)
        qr_preview_caption.setOpenExternalLinks(True)
        qr_preview_caption.setText(
            f'Beispiel-Inhalt: <a href="{_PREVIEW_EXAMPLE_URL}">{_PREVIEW_EXAMPLE_URL}</a> '
            "(dient nur der Vorschau)"
        )
        qr_preview_box = QVBoxLayout()
        qr_preview_box.addWidget(self._qr_preview_label)
        qr_preview_box.addWidget(qr_preview_caption)
        form.addRow("QR-Code-Vorschau:", qr_preview_box)

        self._verify_checkbox = QCheckBox("Nach der Erzeugung zurücklesen und prüfen")
        self._verify_checkbox.setChecked(settings.verify_after_generation)
        form.addRow(self._verify_checkbox)

        root.addLayout(form)

        reset_btn = QPushButton("Auf Standard zurücksetzen")
        reset_btn.clicked.connect(self._reset_to_defaults)
        root.addWidget(reset_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _refresh_logo_preview(self, path: str) -> None:
        pixmap = QPixmap(path.strip()) if path.strip() else QPixmap()
        if pixmap.isNull():
            self._logo_preview.setPixmap(QPixmap())
            self._logo_preview.setText("(keine Vorschau)")
        else:
            self._logo_preview.setText("")
            self._logo_preview.setPixmap(
                pixmap.scaled(
                    96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
            )

    def _pick_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Logo wählen", self._logo_path_edit.text(), "Bilder (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            self._logo_path_edit.setText(path)

    def _reset_to_defaults(self) -> None:
        defaults = QrRenderSettings()
        self._width_spin.setValue(defaults.width_px)
        self._height_spin.setValue(defaults.height_px)
        self._border_spin.setValue(defaults.border_modules)
        self._logo_checkbox.setChecked(defaults.logo_enabled)
        self._logo_path_edit.setText(defaults.logo_path)
        self._logo_max_width_spin.setValue(defaults.logo_max_width_percent)
        self._logo_backplate_spin.setValue(defaults.logo_backplate_width_percent)
        self._verify_checkbox.setChecked(defaults.verify_after_generation)

    def _collect_settings(self) -> QrRenderSettings:
        return replace(
            self._result_settings,
            width_px=self._width_spin.value(),
            height_px=self._height_spin.value(),
            border_modules=self._border_spin.value(),
            logo_enabled=self._logo_checkbox.isChecked(),
            logo_path=self._logo_path_edit.text().strip(),
            logo_max_width_percent=self._logo_max_width_spin.value(),
            logo_backplate_width_percent=self._logo_backplate_spin.value(),
            verify_after_generation=self._verify_checkbox.isChecked(),
        )

    def _schedule_qr_preview_refresh(self, *_args: object) -> None:
        self._qr_preview_timer.start()

    def _refresh_qr_preview(self) -> None:
        try:
            png_bytes = self._service.render_preview(_PREVIEW_EXAMPLE_URL, self._collect_settings())
        except QrModuleError as exc:
            self._qr_preview_label.setPixmap(QPixmap())
            self._qr_preview_label.setText("(Vorschau nicht möglich)")
            self._qr_preview_label.setToolTip(str(exc))
            return
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes)
        self._qr_preview_label.setToolTip("")
        self._qr_preview_label.setText("")
        self._qr_preview_label.setPixmap(
            pixmap.scaled(
                200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )

    def _on_save(self) -> None:
        if self._width_spin.value() <= 0 or self._height_spin.value() <= 0:
            QMessageBox.warning(self, "QR-Einstellungen", "Breite und Höhe müssen größer als 0 sein.")
            return
        updated = self._collect_settings()
        self._service.save_settings(updated)
        self._result_settings = updated
        self.accept()

    def result_settings(self) -> QrRenderSettings:
        return self._result_settings
