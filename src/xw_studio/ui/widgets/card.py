"""Clickable card widget with icon area, title, subtitle, and optional badge."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget


class Card(QFrame):
    """Reusable clickable card for dashboards and tool selectors."""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        accent_color: str = "#c9a24d",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(110)
        self.setStyleSheet(f"""
            Card {{
                border: 1px solid #333;
                border-left: 4px solid {accent_color};
                border-radius: 8px;
            }}
            Card:hover {{
                border-color: {accent_color};
                background-color: rgba(255, 255, 255, 0.03);
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self._title = QLabel(title)
        self._title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {accent_color};")
        layout.addWidget(self._title)

        if subtitle:
            self._subtitle = QLabel(subtitle)
            self._subtitle.setStyleSheet("font-size: 12px; color: #999;")
            self._subtitle.setWordWrap(True)
            layout.addWidget(self._subtitle)

        layout.addStretch()
        self._badge_label: QLabel | None = None

    def set_badge(self, count: int) -> None:
        if count <= 0:
            if self._badge_label:
                self._badge_label.hide()
            return
        if not self._badge_label:
            self._badge_label = QLabel(self)
            self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._badge_label.setFixedSize(24, 24)
            self._badge_label.setStyleSheet(
                "background: #ef5350; color: white; border-radius: 12px; "
                "font-size: 11px; font-weight: bold;"
            )
        self._badge_label.setText(str(count))
        self._badge_label.move(self.width() - 32, 8)
        self._badge_label.show()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)
