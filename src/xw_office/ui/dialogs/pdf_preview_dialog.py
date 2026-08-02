"""Full-screen PDF viewer dialog with zoom and scroll."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

PDF_PREVIEW_DPI = 150


class PdfPreviewDialog(QDialog):
    """PDF viewer with scroll and basic zoom."""

    def __init__(
        self, pdf_path: str | Path, title: str = "PDF-Vorschau",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 960)

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        container = QWidget()
        self._img_layout = QVBoxLayout(container)
        self._img_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        try:
            import fitz
            doc = fitz.open(str(pdf_path))
            for page in doc:
                mat = fitz.Matrix(PDF_PREVIEW_DPI / 72, PDF_PREVIEW_DPI / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888)
                label = QLabel()
                label.setPixmap(QPixmap.fromImage(img))
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._img_layout.addWidget(label)
            doc.close()
        except Exception as exc:
            logger.error("PDF preview failed: %s", exc)
            err = QLabel(f"PDF konnte nicht geladen werden:\n{exc}")
            err.setStyleSheet("color: #ef5350;")
            self._img_layout.addWidget(err)

        scroll.setWidget(container)
        layout.addWidget(scroll)
