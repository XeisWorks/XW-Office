"""Bulk product field editor dialog."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from xw_studio.services.products.field_bulk_service import FieldOperatorType, ProductFieldBulkService

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class BulkFieldEditorDialog(QDialog):
    """Dialog for bulk product field editing with preview."""

    def __init__(self, service: ProductFieldBulkService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._selected_field: str = ""
        self._operator_by_field: dict[str, str] = {}
        self._preview_report = None
        self.setWindowTitle("Produkte: Massenhaft Felder ändern")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)

        # Field selector
        self._field_combo = QComboBox()
        fields = self._service.get_editable_fields()
        for fname, fdef in fields.items():
            self._field_combo.addItem(fdef.label, fname)
        self._field_combo.currentIndexChanged.connect(self._on_field_changed)
        form.addRow("Feld:", self._field_combo)

        # Operator selector
        self._op_combo = QComboBox()
        self._op_combo.addItem("Exakt setzen", FieldOperatorType.SET.value)
        self._op_combo.addItem("Erhöhen um %", FieldOperatorType.ADD_PERCENT.value)
        self._op_combo.addItem("Reduzieren um %", FieldOperatorType.SUBTRACT_PERCENT.value)
        self._op_combo.currentIndexChanged.connect(self._on_operator_changed)
        form.addRow("Operation:", self._op_combo)

        # Value input
        self._value_input = QLineEdit()
        self._value_input.setPlaceholderText("z.B. 10 oder 10.50 oder 'neuer Wert'")
        form.addRow("Wert:", self._value_input)

        lay.addLayout(form)

        # Preview button
        preview_btn = QPushButton("Vorschau anzeigen")
        preview_btn.clicked.connect(self._on_preview_clicked)
        lay.addWidget(preview_btn)

        # Preview output
        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setPlaceholderText("Hier wird die Vorschau angezeigt...")
        self._preview_text.setMaximumHeight(150)
        lay.addWidget(QLabel("Vorschau:"))
        lay.addWidget(self._preview_text)

        # Wix sync checkbox
        self._wix_sync_cb = QComboBox()
        self._wix_sync_cb.addItem("Nur lokal (DB)", False)
        self._wix_sync_cb.addItem("Lokal + Wix Writeback", True)
        form.addRow("Sync:", self._wix_sync_cb)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        # Initially update operator availability
        self._on_field_changed()

    def _on_field_changed(self) -> None:
        """Update operator combo based on selected field."""
        current_field = self._field_combo.currentData()
        if not current_field:
            return

        fields = self._service.get_editable_fields()
        field_def = fields.get(current_field)
        if not field_def:
            return

        # Save current operator for this field
        self._operator_by_field[current_field] = self._op_combo.currentData() or FieldOperatorType.SET.value

        # Reset operator combo based on field type
        self._op_combo.blockSignals(True)
        self._op_combo.clear()
        self._op_combo.addItem("Exakt setzen", FieldOperatorType.SET.value)

        # Allow percentage operators only for numeric fields
        if field_def.field_type in ("number", "decimal"):
            self._op_combo.addItem("Erhöhen um %", FieldOperatorType.ADD_PERCENT.value)
            self._op_combo.addItem("Reduzieren um %", FieldOperatorType.SUBTRACT_PERCENT.value)

        # Restore previous operator if available
        prev_op = self._operator_by_field.get(current_field, FieldOperatorType.SET.value)
        idx = self._op_combo.findData(prev_op)
        self._op_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._op_combo.blockSignals(False)

        # Update value input placeholder
        if field_def.field_type == "number":
            self._value_input.setPlaceholderText("Zahl eingeben (z.B. 42)")
        elif field_def.field_type == "decimal":
            self._value_input.setPlaceholderText("Dezimalzahl eingeben (z.B. 19.99)")
        else:
            self._value_input.setPlaceholderText("Text eingeben")

    def _on_operator_changed(self) -> None:
        """Update operator storage for current field."""
        current_field = self._field_combo.currentData()
        if current_field:
            self._operator_by_field[current_field] = self._op_combo.currentData() or FieldOperatorType.SET.value

    def _on_preview_clicked(self) -> None:
        """Show preview of the field update."""
        field_name = self._field_combo.currentData()
        if not field_name:
            QMessageBox.warning(self, "Vorschau", "Bitte ein Feld auswählen.")
            return

        operator = self._op_combo.currentData()
        if not operator:
            QMessageBox.warning(self, "Vorschau", "Bitte eine Operation auswählen.")
            return

        value = self._value_input.text().strip()
        if not value:
            QMessageBox.warning(self, "Vorschau", "Bitte einen Wert eingeben.")
            return

        # Get selected SKUs from parent view
        skus = self._get_selected_skus()
        if not skus:
            QMessageBox.warning(self, "Vorschau", "Keine Produkte in der Inventar-Tabelle ausgewählt.")
            return

        try:
            self._preview_report = self._service.preview_field_update(
                skus=skus,
                field_name=field_name,
                operator=operator,
                value=value,
            )
            self._show_preview(self._preview_report)
        except ValueError as exc:
            QMessageBox.warning(self, "Vorschau", f"Fehler beim Berechnen der Vorschau:\n{exc}")
            self._preview_report = None

    def _show_preview(self, report: object) -> None:
        """Display preview report in text area."""
        if not hasattr(report, "changed"):
            self._preview_text.setText("Fehler beim Laden der Vorschau")
            return

        fields = self._service.get_editable_fields()
        field_def = fields.get(report.field_name, None)  # type: ignore[union-attr]
        field_label = field_def.label if field_def else report.field_name  # type: ignore[union-attr]

        lines = [
            f"Feld: {field_label}",
            f"Operation: {report.operator}",  # type: ignore[union-attr]
            f"Neuer Wert: {report.value}",  # type: ignore[union-attr]
            "",
            f"Angefordert: {report.requested}",  # type: ignore[union-attr]
            f"Würden geändert: {report.changed}",  # type: ignore[union-attr]
            f"Übersprungen: {report.skipped}",  # type: ignore[union-attr]
            f"Fehler: {report.failed}",  # type: ignore[union-attr]
        ]
        
        if report.items:  # type: ignore[union-attr]
            lines.append("\nÄnderungen:")
            for item in report.items[:20]:  # type: ignore[union-attr]
                if item.status != "skipped":  # type: ignore[attr-defined]
                    lines.append(
                        f"  {item.sku}: {item.old_value} → {item.new_value} ({item.status})"  # type: ignore[attr-defined]
                    )
            if len(report.items) > 20:  # type: ignore[union-attr]
                lines.append(f"  ... und {len(report.items) - 20} weitere")  # type: ignore[union-attr]

        self._preview_text.setText("\n".join(lines))

    def _get_selected_skus(self) -> list[str]:
        """Get list of selected product SKUs (called by parent)."""
        # This will be called by the parent view
        # We'll return a placeholder that gets populated by parent
        return getattr(self, "_selected_skus", [])

    def set_selected_skus(self, skus: list[str]) -> None:
        """Set the list of selected SKUs from parent."""
        self._selected_skus = skus

    def get_field_and_value(self) -> tuple[str, str, str, bool]:
        """Get selected field, operator, value, and sync_wix flag."""
        field = self._field_combo.currentData() or ""
        operator = self._op_combo.currentData() or ""
        value = self._value_input.text().strip()
        sync_wix = self._wix_sync_cb.currentData()
        return field, operator, value, bool(sync_wix)
