"""Modal progress dialog with cancel button."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ProgressDialog(QDialog):
    """Modal dialog showing task progress."""

    def __init__(
        self, title: str = "Bitte warten...",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)

        self._label = QLabel(title)
        self._label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self._label)

        self._progress = QProgressBar()
        layout.addWidget(self._progress)

        self._cancel_btn = QPushButton("Abbrechen")
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._cancel_btn)

        self._cancelled = False

    def set_progress(self, value: int, message: str = "") -> None:
        self._progress.setValue(value)
        if message:
            self._label.setText(message)

    def set_indeterminate(self) -> None:
        self._progress.setRange(0, 0)

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def reject(self) -> None:
        self._cancelled = True
        super().reject()
