"""Yes/No/Cancel confirmation dialog."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget


class ConfirmDialog(QDialog):
    """Simple confirmation dialog with customizable text."""

    def __init__(
        self, title: str, message: str,
        cancel_button: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 14px; padding: 12px;")
        layout.addWidget(label)

        buttons = QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        if cancel_button:
            buttons |= QDialogButtonBox.StandardButton.Cancel

        bbox = QDialogButtonBox(buttons)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)
