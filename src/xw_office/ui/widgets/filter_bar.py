"""Horizontal filter bar with combo boxes and chips."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget


class FilterBar(QWidget):
    """Horizontal bar with labeled combo filters."""

    filter_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)
        self._combos: dict[str, QComboBox] = {}

    def add_filter(self, key: str, label: str, options: list[str]) -> QComboBox:
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 12px; color: #999;")
        self._layout.addWidget(lbl)

        combo = QComboBox()
        combo.addItems(options)
        combo.setMinimumWidth(120)
        combo.currentTextChanged.connect(lambda text, k=key: self.filter_changed.emit(k, text))
        self._combos[key] = combo
        self._layout.addWidget(combo)
        return combo

    def add_stretch(self) -> None:
        self._layout.addStretch()

    def value(self, key: str) -> str:
        combo = self._combos.get(key)
        return combo.currentText() if combo else ""
