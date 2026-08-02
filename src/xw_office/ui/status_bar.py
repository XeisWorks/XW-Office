"""Global status bar with printer status indicator."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QStatusBar


class OfficeStatusBar(QStatusBar):
    """Extended status bar with printer traffic light."""

    def __init__(self) -> None:
        super().__init__()
        self._printer_label = QLabel("● Drucker")
        self._printer_label.setStyleSheet("color: #888; padding: 0 8px;")
        self.addPermanentWidget(self._printer_label)

    def set_printer_status(self, color: str, tooltip: str) -> None:
        color_map = {"green": "#66bb6a", "yellow": "#ffa726", "red": "#ef5350"}
        css_color = color_map.get(color, "#888")
        self._printer_label.setStyleSheet(f"color: {css_color}; padding: 0 8px;")
        self._printer_label.setToolTip(tooltip)
