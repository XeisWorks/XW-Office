"""Dedicated Stornos & Gutschriften view."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
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
from shiboken6 import isValid

from xw_office.core.worker import BackgroundWorker
from xw_office.services.flow_api import FlowRefundsClient
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.sevdesk.invoice_client import InvoiceClient
from xw_office.services.sevdesk.refund_client import SevDeskRefundClient
from xw_office.services.wix.client import WixOrdersClient


class RefundsDialog(QDialog):
    def __init__(self, container: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._rows: list[dict[str, Any]] = []
        self._worker: BackgroundWorker | None = None
        self._write_worker: BackgroundWorker | None = None
        self._closing = False
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

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._write_is_running():
            event.ignore()
            return
        self._closing = True
        super().closeEvent(event)

    def reject(self) -> None:
        if self._write_is_running():
            return
        self._closing = True
        super().reject()

    def accept(self) -> None:
        if self._write_is_running():
            return
        self._closing = True
        super().accept()

    def _write_is_running(self) -> bool:
        return self._write_worker is not None

    def _load(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        client = self._container.resolve(FlowRefundsClient)
        self._start_worker(lambda: client.list_refunds(limit=250), self._on_rows_loaded)

    def _on_rows_loaded(self, result: object) -> None:
        self._rows = list(result) if isinstance(result, list) else []
        self._table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            values = [
                row.get("wix_refund_id", ""),
                row.get("wix_order_number") or row.get("wix_order_id", ""),
                f"{float(row.get('amount') or 0):.2f} {row.get('currency') or ''}".strip(),
                row.get("wix_refund_status", ""),
                row.get("sevdesk_action", ""),
                row.get("process_status", ""),
                row.get("sevdesk_credit_note_id")
                or row.get("sevdesk_cancellation_invoice_id")
                or row.get("sevdesk_invoice_id")
                or "",
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

    def _start_worker(
        self,
        job: Callable[[], Any],
        on_result: Callable[[object], None],
        *,
        blocks_close: bool = False,
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        worker = BackgroundWorker(job)
        self._worker = worker
        if blocks_close:
            self._write_worker = worker
        worker.signals.result.connect(
            lambda result: on_result(result) if not self._closing and isValid(self) else None
        )
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda current=worker: self._worker_finished(current))
        worker.start()

    def _worker_error_title(self) -> str:
        return "Refunds"

    def _on_worker_error(self, exc: Exception) -> None:
        if not self._closing and isValid(self):
            QMessageBox.warning(self, self._worker_error_title(), str(exc))

    def _worker_finished(self, worker: BackgroundWorker) -> None:
        is_current = self._worker is worker
        if is_current:
            self._worker = None
        if self._write_worker is worker:
            self._write_worker = None
        if is_current and not self._closing and isValid(self):
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._table.setEnabled(not busy)

    def _credit_note_id(self, index: int) -> str:
        row = self._rows[index]
        if row.get("process_status") not in {"done_creditnote", "done_creditnote_partial"}:
            return ""
        return str(row.get("sevdesk_credit_note_id") or "").strip()

    def _open_pdf(self, index: int) -> None:
        credit_note_id = self._credit_note_id(index)
        if not credit_note_id:
            return
        client = self._container.resolve(SevDeskRefundClient)

        def job() -> str:
            pdf = client.get_credit_note_pdf(credit_note_id)
            descriptor, filename = tempfile.mkstemp(prefix="xw-gutschrift-", suffix=".pdf")
            os.close(descriptor)
            path = Path(filename)
            path.write_bytes(pdf)
            return str(path)

        def open_file(filename: object) -> None:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(filename))):
                QMessageBox.warning(self, "Gutschrift-PDF", "PDF konnte nicht geoeffnet werden")

        self._start_worker(job, open_file)

    def _send_mail(self, index: int) -> None:
        row = dict(self._rows[index])
        credit_note_id = self._credit_note_id(index)
        if not credit_note_id:
            return
        invoice_id = str(row.get("sevdesk_invoice_id") or "")
        order_reference = str(row.get("wix_order_number") or "").strip()
        sevdesk = self._container.resolve(SevDeskRefundClient)
        invoice_client = self._container.resolve(InvoiceClient)
        wix_client = self._container.resolve(WixOrdersClient)
        processing = self._container.resolve(InvoiceProcessingService)

        def prepare() -> dict[str, str]:
            note = sevdesk.fetch_credit_note(credit_note_id)
            number = str(note.get("creditNumber") or note.get("invoiceNumber") or credit_note_id)
            invoice_result = invoice_client.fetch_invoice_by_id(invoice_id) if invoice_id else {}
            invoice = invoice_result if isinstance(invoice_result, dict) else {}
            wix_summary: dict[str, Any] = {}
            if order_reference:
                try:
                    wix_summary = wix_client.resolve_order_summary(order_reference)
                except Exception:  # noqa: BLE001 - recipient can still be entered manually.
                    pass
            email = str(wix_summary.get("wix_customer_email") or "").strip() or _find_email(invoice)
            name = str(wix_summary.get("wix_customer_name") or invoice.get("name") or "Kunde").strip()
            subject, body = processing.build_credit_note_mail_content(number, customer_name=name)
            return {"number": number, "email": email, "subject": subject, "body": body}

        self._start_worker(prepare, lambda draft: self._confirm_credit_note_mail(draft, credit_note_id))

    def _confirm_credit_note_mail(self, payload: object, credit_note_id: str) -> None:
        if not isinstance(payload, dict):
            return
        draft = {str(key): str(value or "") for key, value in payload.items()}
        email = draft.get("email", "").strip()
        if not email:
            email, accepted = QInputDialog.getText(self, "Gutschrift senden", "E-Mail-Adresse:")
            if not accepted or not email.strip():
                return
        number = draft.get("number", credit_note_id)
        if QMessageBox.question(
            self,
            "Gutschrift senden",
            f"Gutschrift {number} an {email.strip()} senden?",
        ) != QMessageBox.StandardButton.Yes:
            return
        sevdesk = self._container.resolve(SevDeskRefundClient)
        processing = self._container.resolve(InvoiceProcessingService)
        subject = draft.get("subject", "")
        body = draft.get("body", "")

        def send() -> str:
            pdf = sevdesk.get_credit_note_pdf(credit_note_id)
            processing.send_credit_note_mail(
                credit_note_id,
                recipient=email.strip(),
                credit_note_number=number,
                subject=subject,
                text_body=body,
                pdf_bytes=pdf,
            )
            return email.strip()

        def on_sent(recipient: object) -> None:
            QMessageBox.information(
                self,
                "Gutschrift gesendet",
                f"Die Gutschrift wurde an {recipient} gesendet.",
            )

        self._start_worker(send, on_sent, blocks_close=True)


def _find_email(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    sources: list[dict[str, Any]] = [value]
    contact = value.get("contact")
    if isinstance(contact, dict):
        sources.append(contact)
    for source in sources:
        for key in ("email", "toEmail", "contactEmail", "emailAddress"):
            candidate = str(source.get(key) or "").strip()
            if "@" in candidate:
                return candidate
    return ""
