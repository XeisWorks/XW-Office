"""Slide-in side panel for item details."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class DetailPanel(QFrame):
    """Slide-in panel for showing details of a selected item."""

    def __init__(self, title: str = "Details", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(320)
        self.setMaximumWidth(480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 8)

        top_row = QWidget()
        top_layout = QVBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel(title)
        self._title.setStyleSheet("font-size: 16px; font-weight: bold;")
        top_layout.addWidget(self._title)
        header_layout.addWidget(top_row)

        close_btn = QPushButton("Schliessen")
        close_btn.clicked.connect(self.hide)
        header_layout.addWidget(close_btn)
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(16, 8, 16, 16)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._content)
        outer.addWidget(scroll, stretch=1)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def set_title(self, title: str) -> None:
        self._title.setText(title)
