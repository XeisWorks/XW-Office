"""Dedicated Stornos & Gutschriften view."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.services.flow_api import FlowRefundsClient
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.mailing.service import MailAttachment, MailDeliveryService
from xw_office.services.sevdesk.invoice_client import InvoiceClient
from xw_office.services.sevdesk.refund_client import SevDeskRefundClient
from xw_office.services.wix.client import WixOrdersClient


class RefundsDialog(QDialog):
    def __init__(self, container: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._rows: list[dict[str, Any]] = []
        self.setWindowTitle("Stornos & Gutschriften")
        self.resize(980, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Refunds werden ausschließlich in Wix erstellt. Hier siehst du den Beleg- und Prüfstatus der API."))
        self._table = QTableWidget(0, 8, self)
        self._table.setHorizontalHeaderLabels(["Refund", "Order", "Betrag", "Wix", "Aktion", "Status", "sevDesk", "Aktionen"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._load()

    def _load(self) -> None:
        try:
            self._rows = self._container.resolve(FlowRefundsClient).list_refunds(limit=250)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Refunds", f"Refund-Liste konnte nicht geladen werden:\n\n{exc}")
            self._rows = []
        self._table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            values = [
                row.get("wix_refund_id", ""),
                row.get("wix_order_number") or row.get("wix_order_id", ""),
                f"{float(row.get('amount') or 0):.2f} {row.get('currency') or ''}".strip(),
                row.get("wix_refund_status", ""),
                row.get("sevdesk_action", ""),
                row.get("process_status", ""),
                row.get("sevdesk_credit_note_id") or row.get("sevdesk_cancellation_invoice_id") or row.get("sevdesk_invoice_id") or "",
            ]
            for column, value in enumerate(values):
                self._table.setItem(row_index, column, QTableWidgetItem(str(value)))
            actions = QWidget(self._table)
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(2, 0, 2, 0)
            pdf = QPushButton("PDF")
            pdf.clicked.connect(lambda _checked=False, index=row_index: self._open_pdf(index))
            mail = QPushButton("Mail")
            mail.clicked.connect(lambda _checked=False, index=row_index: self._send_mail(index))
            finalized = row.get("process_status") in {"done_creditnote", "done_creditnote_partial"}
            pdf.setEnabled(finalized and bool(row.get("sevdesk_credit_note_id")))
            mail.setEnabled(finalized and bool(row.get("sevdesk_credit_note_id")))
            action_layout.addWidget(pdf)
            action_layout.addWidget(mail)
            self._table.setCellWidget(row_index, 7, actions)

    def _credit_note_id(self, index: int) -> str:
        row = self._rows[index]
        if row.get("process_status") not in {"done_creditnote", "done_creditnote_partial"}:
            return ""
        return str(row.get("sevdesk_credit_note_id") or "").strip()

    def _open_pdf(self, index: int) -> None:
        credit_note_id = self._credit_note_id(index)
        if not credit_note_id:
            return
        try:
            pdf = self._container.resolve(SevDeskRefundClient).get_credit_note_pdf(credit_note_id)
            descriptor, filename = tempfile.mkstemp(prefix="xw-gutschrift-", suffix=".pdf")
            os.close(descriptor)
            path = Path(filename)
            path.write_bytes(pdf)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise RuntimeError("PDF konnte nicht geöffnet werden")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Gutschrift-PDF", str(exc))

    def _send_mail(self, index: int) -> None:
        row = self._rows[index]
        credit_note_id = self._credit_note_id(index)
        if not credit_note_id:
            return
        try:
            sevdesk = self._container.resolve(SevDeskRefundClient)
            note = sevdesk.fetch_credit_note(credit_note_id)
            number = str(note.get("creditNumber") or note.get("invoiceNumber") or credit_note_id)
            invoice_id = str(row.get("sevdesk_invoice_id") or "")
            invoice = self._container.resolve(InvoiceClient).fetch_invoice_by_id(invoice_id) if invoice_id else {}
            wix_summary: dict[str, Any] = {}
            order_reference = str(row.get("wix_order_number") or "").strip()
            if order_reference:
                try:
                    wix_summary = self._container.resolve(WixOrdersClient).resolve_order_summary(order_reference)
                except Exception:  # noqa: BLE001 - explicit recipient prompt remains available.
                    pass
            email = str(wix_summary.get("wix_customer_email") or "").strip() or _find_email(invoice)
            if not email:
                email, accepted = QInputDialog.getText(self, "Gutschrift senden", "E-Mail-Adresse:")
                if not accepted or not email.strip():
                    return
            customer_name = str(wix_summary.get("wix_customer_name") or invoice.get("name") or "Kunde").strip()
            subject, body = self._container.resolve(InvoiceProcessingService).build_credit_note_mail_content(number, customer_name=customer_name)
            answer = QMessageBox.question(self, "Gutschrift senden", f"Gutschrift {number} an {email.strip()} senden?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            pdf = sevdesk.get_credit_note_pdf(credit_note_id)
            self._container.resolve(MailDeliveryService).send_mail(
                to_email=email.strip(),
                subject=subject,
                text_body=body,
                html_body=self._container.resolve(MailDeliveryService).plain_text_to_html(body),
                attachments=[MailAttachment(filename=f"{number}.pdf", content=pdf)],
            )
            QMessageBox.information(self, "Gutschrift gesendet", f"Die Gutschrift wurde an {email.strip()} gesendet.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Gutschrift senden", str(exc))


def _find_email(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for source in (value, value.get("contact") if isinstance(value.get("contact"), dict) else {}):
        for key in ("email", "toEmail", "contactEmail", "emailAddress"):
            candidate = str(source.get(key) or "").strip()
            if "@" in candidate:
                return candidate
    return ""
