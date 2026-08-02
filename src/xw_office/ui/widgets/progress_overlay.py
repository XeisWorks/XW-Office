"""Semi-transparent loading spinner overlay."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class ProgressOverlay(QWidget):
    """Overlay with spinner and optional message."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: rgba(0, 0, 0, 0.5);")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedWidth(200)
        layout.addWidget(self._progress)

        self._label = QLabel("Laden...")
        self._label.setStyleSheet("color: white; font-size: 14px;")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)
        self.hide()

    def show_with_message(self, message: str = "Laden...") -> None:
        self._label.setText(message)
        if self.parent():
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
        self.show()
        self.raise_()
