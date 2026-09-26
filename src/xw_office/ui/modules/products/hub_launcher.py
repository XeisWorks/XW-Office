"""Safe desktop entry point for the shared Product Hub WebUI."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class ProductHubLauncherView(QWidget):
    """Browser fallback deliberately never puts the bearer token in a URL."""

    def __init__(self, *, hub_base_url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._url = hub_base_url.rstrip("/") + "/app/"
        layout = QVBoxLayout(self)
        title = QLabel("Product Hub")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "Die gemeinsame Produktoberfläche wird im Standardbrowser geöffnet. "
            "Zugangsdaten werden niemals in einer URL übergeben."
        ))
        open_button = QPushButton("Product Hub öffnen")
        open_button.clicked.connect(self.open_hub)
        layout.addWidget(open_button)
        layout.addStretch()

    def open_hub(self) -> None:
        QDesktopServices.openUrl(QUrl(self._url))
