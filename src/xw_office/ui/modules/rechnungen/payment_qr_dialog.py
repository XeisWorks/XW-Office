from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xw_office.services.transfers.models import TransferPaymentData


class PaymentQrDialog(QDialog):
    """Show generated EPC QR PNG and payment payload."""

    def __init__(self, qr_path: Path, payment: TransferPaymentData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._qr_path = qr_path
        self._payment = payment
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("EPC QR-Code")
        self.setMinimumSize(560, 560)

        layout = QVBoxLayout(self)

        self._image = QLabel("QR konnte nicht geladen werden")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(str(self._qr_path))
        if not pix.isNull():
            self._image.setPixmap(pix.scaled(340, 340, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(self._image)

        details = QLabel(
            "\n".join(
                [
                    f"Empfaenger: {self._payment.recipient}",
                    f"IBAN: {self._payment.iban}",
                    f"BIC: {self._payment.bic or '-'}",
                    f"Betrag: {self._payment.amount or '-'} EUR",
                    f"Verwendungszweck: {self._payment.remittance_text or '-'}",
                    f"Datei: {self._qr_path}",
                ]
            )
        )
        details.setWordWrap(True)
        layout.addWidget(details)

        row = QHBoxLayout()
        btn_open = QPushButton("PNG oeffnen")
        btn_open.clicked.connect(self._open_png)
        row.addWidget(btn_open)

        btn_folder = QPushButton("Ordner oeffnen")
        btn_folder.clicked.connect(self._open_folder)
        row.addWidget(btn_folder)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _open_png(self) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._qr_path))):
            QMessageBox.warning(self, "QR", "PNG konnte nicht geoeffnet werden.")

    def _open_folder(self) -> None:
        folder = self._qr_path.parent
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(self, "QR", "Ordner konnte nicht geoeffnet werden.")
