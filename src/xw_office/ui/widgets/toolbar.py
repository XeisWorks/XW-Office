"""Configurable horizontal action toolbar."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class Toolbar(QWidget):
    """Horizontal toolbar with action buttons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._buttons: dict[str, QPushButton] = {}

    def add_button(
        self, key: str, label: str, style: str = "", tooltip: str = "",
    ) -> QPushButton:
        btn = QPushButton(label)
        if style:
            btn.setStyleSheet(style)
        if tooltip:
            btn.setToolTip(tooltip)
        btn.setMinimumHeight(36)
        self._buttons[key] = btn
        self._layout.addWidget(btn)
        return btn

    def add_stretch(self) -> None:
        self._layout.addStretch()

    def button(self, key: str) -> QPushButton | None:
        return self._buttons.get(key)
