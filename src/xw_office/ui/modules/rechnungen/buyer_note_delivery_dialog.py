"""Delivery-note preview and explicit actions for the START buyer-note review."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.invoice_processing.buyer_notes import BuyerNoteCase
from xw_office.services.mailing.outlook_compose import open_classic_outlook_draft
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.secrets.service import SecretService
from xw_office.services.sendungen.delivery_note import DeliveryNoteContext, DeliveryNoteService
from xw_office.services.sendungen.service import OffeneSendungenService


class BuyerNoteDeliveryDialog(QDialog):
    """Preview source data, edit the AI suggestion, then choose an output."""

    def __init__(self, case: BuyerNoteCase, address: tuple[str, ...], manual_note: str,
                 container: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lieferschein")
        self.resize(760, 620)
        self._case = case
        self._address = address
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._output: str = ""
        self._pdf: Path | None = None
        self._suggest_original = ""
        self._build_ui(manual_note)
        if not manual_note:
            self._suggest()

    @property
    def output(self) -> str:
        return self._output

    @property
    def manual_note(self) -> str:
        return self._manual.toPlainText().strip()

    def _build_ui(self, manual_note: str) -> None:
        root = QVBoxLayout(self)
        title = QLabel(f"{self._case.customer_name} · {self._case.invoice_number or self._case.invoice_id}")
        title.setStyleSheet("font-size: 16px; font-weight: 600")
        root.addWidget(title)
        columns = QHBoxLayout()
        address = QPlainTextEdit("\n".join(self._address))
        address.setReadOnly(True)
        address.setMaximumWidth(300)
        columns.addWidget(self._section("Lieferadresse", address))
        products = QPlainTextEdit("\n".join(
            f"{p.quantity} × {p.name or p.sku or 'Produkt'}" + (f" · {p.sku}" if p.sku and p.name else "")
            for p in self._case.products
        ))
        products.setReadOnly(True)
        columns.addWidget(self._section("Positionen", products), 1)
        root.addLayout(columns, 1)
        note = QPlainTextEdit(self._case.note_text)
        note.setReadOnly(True)
        root.addWidget(self._section("Käufernotiz (Original)", note), 1)
        self._manual = QPlainTextEdit(manual_note)
        self._manual.setPlaceholderText("Optionaler Lieferschein-Zusatz")
        self._manual.setMaximumHeight(90)
        root.addWidget(self._section("Zusatztext (bearbeitbar)", self._manual))
        self._status = QLabel("")
        root.addWidget(self._status)
        actions = QHBoxLayout()
        self._ai = QPushButton("✦ Vorschlag erneuern")
        self._ai.clicked.connect(self._suggest)
        actions.addWidget(self._ai)
        self._open = QPushButton("◉ PDF öffnen")
        self._open.clicked.connect(lambda: self._prepare("open"))
        actions.addWidget(self._open)
        self._print = QPushButton("⎙ Drucken")
        self._print.clicked.connect(lambda: self._prepare("print"))
        actions.addWidget(self._print)
        self._mail = QPushButton("✉ Mail-Entwurf")
        self._mail.clicked.connect(lambda: self._prepare("mail"))
        actions.addWidget(self._mail)
        root.addLayout(actions)
        bottom = QHBoxLayout()
        bottom.addStretch()
        self._schedule = QPushButton("Für START vormerken")
        self._schedule.clicked.connect(self._schedule_for_start)
        bottom.addWidget(self._schedule)
        close = QPushButton("Schließen")
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        root.addLayout(bottom)
        self._action_buttons = (self._ai, self._open, self._print, self._mail, self._schedule)

    @staticmethod
    def _section(label: str, editor: QPlainTextEdit) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label))
        layout.addWidget(editor)
        return panel

    def _context(self) -> DeliveryNoteContext:
        return DeliveryNoteContext(
            invoice_number=self._case.invoice_number,
            order_reference=self._case.order_reference,
            customer_name=self._case.customer_name,
            address_lines=self._address,
            products=self._case.products,
            buyer_note=self._case.note_text,
            manual_note=self.manual_note,
        )

    def _run(self, label: str, job: object, ready: object) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        for button in self._action_buttons:
            button.setEnabled(False)
        self._status.setText(label)
        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(ready)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self) -> None:
        self._worker = None
        for button in self._action_buttons:
            button.setEnabled(True)
        if self._output == "printed":
            self.accept()

    def _on_error(self, exc: Exception) -> None:
        self._status.setText("Aktion fehlgeschlagen")
        QMessageBox.warning(self, "Lieferschein", str(exc))

    def _suggest(self) -> None:
        context = self._context()
        self._suggest_original = self.manual_note
        def job() -> str:
            secrets = self._container.resolve(SecretService)
            return DeliveryNoteService().suggest_manual_note(
                context, str(secrets.get_secret("OPENAI_API_KEY") or ""),
            )
        self._run("OpenAI-Vorschlag wird erstellt…", job, self._on_suggestion)

    def _on_suggestion(self, value: object) -> None:
        if self.manual_note == self._suggest_original:
            self._manual.setPlainText(str(value or ""))
            self._status.setText("Vorschlag bereit" if value else "Kein passender Lieferhinweis in der Käufernotiz")
        else:
            self._status.setText("Eigener Zusatztext beibehalten")

    def _prepare(self, action: str) -> None:
        if action == "mail" and not self._case.customer_email:
            QMessageBox.warning(self, "Lieferschein", "Keine Kunden-E-Mail-Adresse vorhanden.")
            return
        context = self._context()
        def job() -> tuple[str, Path]:
            path = DeliveryNoteService().generate_pdf(context)
            if action == "print":
                self._container.resolve(OffeneSendungenService).print_delivery_note(
                    path, printing=self._container.config.printing,
                    print_queue=self._container.resolve(PrintQueueService), wait=True,
                )
            elif action == "mail":
                sender = str(self._container.resolve(SecretService).get_secret("OUTLOOK_SENDER_EMAIL") or "")
                open_classic_outlook_draft(
                    to_email=self._case.customer_email,
                    subject=f"Lieferschein zu Bestellung {self._case.order_reference or self._case.invoice_number}",
                    sender_smtp=sender,
                    body="Guten Tag,\n\nanbei der Lieferschein zu Ihrer Bestellung.\n\nMit freundlichen Grüßen\nXeisWorks",
                    attachments=[str(path)],
                )
            return action, path
        self._run("Lieferschein wird vorbereitet…", job, self._on_prepared)

    def _on_prepared(self, value: object) -> None:
        action, path = value
        self._pdf = path
        if action == "open":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            self._status.setText("PDF geöffnet")
        elif action == "print":
            self._status.setText("Gedruckt. Für diesen START-Lauf nicht erneut vormerken.")
            self._output = "printed"
        else:
            self._status.setText("Outlook-Entwurf geöffnet. Versand bitte in Outlook prüfen.")

    def _schedule_for_start(self) -> None:
        self._output = "schedule"
        self.accept()
