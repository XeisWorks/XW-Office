"""Small, accessible result dialog shared by tax operations."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class OperationResultDialog(QDialog):
    def __init__(self, parent, *, tone: str, title: str, summary: str, context: str = "", details: str = "",
                 actions: list[tuple[str, Callable[[], None]]] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        layout = QVBoxLayout(self)
        symbol = {"success": "✓", "neutral": "●", "warning": "!", "error": "×"}.get(tone, "●")
        icon = QLabel(symbol)
        icon.setAccessibleName(f"Ergebnis: {tone}")
        icon.setStyleSheet("font-size: 32px; font-weight: 700;")
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        heading = QLabel(summary)
        heading.setWordWrap(True)
        heading.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(heading)
        if context:
            context_label = QLabel(context)
            context_label.setWordWrap(True)
            layout.addWidget(context_label)
        if details:
            detail = QPlainTextEdit(details)
            detail.setReadOnly(True)
            detail.setVisible(False)
            toggle = QPushButton("Technische Details anzeigen")
            toggle.setCheckable(True)
            toggle.toggled.connect(lambda checked: (detail.setVisible(checked), toggle.setText("Technische Details ausblenden" if checked else "Technische Details anzeigen")))
            layout.addWidget(toggle)
            layout.addWidget(detail)
        for label, callback in actions or []:
            action = QPushButton(label)
            def trigger(_checked: bool = False, *, button: QPushButton = action, handler: Callable[[], None] = callback, button_label: str = label) -> None:
                button.setEnabled(False)
                button.setText(f"{button_label} …")
                handler()
            action.clicked.connect(trigger)
            layout.addWidget(action)
        close = QPushButton("✓  Schließen")
        close.setAccessibleName("Schließen")
        close.setToolTip("Ergebnisdialog schließen")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.resize(460, 260)
