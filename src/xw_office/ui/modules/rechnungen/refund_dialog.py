"""Refund confirmation dialog for Rechnungen actions column."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from xw_office.services.sevdesk.invoice_client import InvoiceSummary


class RefundDialog(QDialog):
    """Confirm full refund flow: sevDesk cancellation + Wix payment refund."""

    def __init__(self, summary: InvoiceSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rückerstattung starten")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        info = QLabel(
            "Es wird eine vollständige Rückerstattung für diese Rechnung gestartet.\n"
            "Ablauf: sevDesk Stornorechnung erstellen, danach Wix-Zahlung erstatten."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        details = QLabel(
            f"Rechnung: {summary.invoice_number or summary.id}\n"
            f"Kunde: {summary.contact_name or '—'}\n"
            f"Order-Ref: {summary.order_reference or '—'}"
        )
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(details)

        warning = QLabel("Hinweis: sevDesk cancelInvoice ist nicht reversibel.")
        warning.setStyleSheet("color: #b45309;")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self._send_customer_mail = QCheckBox("Kundenmail über Wix senden")
        self._send_customer_mail.setChecked(True)
        self._send_customer_mail.setEnabled(bool(summary.order_reference.strip()))
        layout.addWidget(self._send_customer_mail)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("Rückerstattung ausführen")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def send_customer_mail(self) -> bool:
        return bool(self._send_customer_mail.isChecked())
