"""Printer traffic light status widget."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from xw_office.core.types import PrinterStatus


class PrinterStatusWidget(QWidget):
    """Compact traffic light indicator for printer availability."""

    _COLORS = {
        PrinterStatus.GREEN: ("#66bb6a", "Drucker bereit"),
        PrinterStatus.YELLOW: ("#ffa726", "Drucker teilweise verfuegbar"),
        PrinterStatus.RED: ("#ef5350", "Kein Drucker - Druck deaktiviert"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._dot = QLabel("●")
        self._dot.setStyleSheet("font-size: 14px; color: #888;")
        layout.addWidget(self._dot)

        self._label = QLabel("Drucker")
        self._label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self._label)

    def set_status(self, status: PrinterStatus) -> None:
        color, tooltip = self._COLORS.get(status, ("#888", "Unbekannt"))
        self._dot.setStyleSheet(f"font-size: 14px; color: {color};")
        self._label.setStyleSheet(f"font-size: 12px; color: {color};")
        self.setToolTip(tooltip)
