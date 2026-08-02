"""Labeled form input fields."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QWidget,
)


class FormFields(QWidget):
    """Form layout with helper methods for adding labeled fields."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._fields: dict[str, QWidget] = {}

    def add_text(self, key: str, label: str, placeholder: str = "") -> QLineEdit:
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        self._fields[key] = field
        self._layout.addRow(label, field)
        return field

    def add_number(self, key: str, label: str, min_val: int = 0, max_val: int = 999999) -> QSpinBox:
        field = QSpinBox()
        field.setRange(min_val, max_val)
        self._fields[key] = field
        self._layout.addRow(label, field)
        return field

    def add_decimal(self, key: str, label: str, decimals: int = 2) -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setDecimals(decimals)
        field.setRange(0, 999999.99)
        self._fields[key] = field
        self._layout.addRow(label, field)
        return field

    def add_combo(self, key: str, label: str, options: list[str]) -> QComboBox:
        field = QComboBox()
        field.addItems(options)
        self._fields[key] = field
        self._layout.addRow(label, field)
        return field

    def add_date(self, key: str, label: str) -> QDateEdit:
        field = QDateEdit()
        field.setCalendarPopup(True)
        self._fields[key] = field
        self._layout.addRow(label, field)
        return field

    def field(self, key: str) -> QWidget | None:
        return self._fields.get(key)
