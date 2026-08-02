"""Small notification badge overlay widget."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget


class Badge(QLabel):
    """Small red circle badge with count."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(22, 22)
        self.setStyleSheet(
            "background: #ef5350; color: white; border-radius: 11px; "
            "font-size: 10px; font-weight: bold;"
        )
        self.hide()

    def set_count(self, count: int) -> None:
        if count <= 0:
            self.hide()
            return
        self.setText(str(min(count, 99)))
        self.show()
