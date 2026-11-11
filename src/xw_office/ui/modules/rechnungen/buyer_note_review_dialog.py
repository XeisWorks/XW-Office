"""START confirmation dialog for source-aware buyer notes."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.container import Container
from xw_office.core.worker import BackgroundWorker
from xw_office.services.mailing.outlook_compose import open_classic_outlook_draft
from xw_office.services.secrets.service import SecretService
from xw_office.ui.modules.rechnungen.buyer_note_delivery_dialog import BuyerNoteDeliveryDialog
from xw_office.services.invoice_processing.buyer_notes import (
    BUYER_NOTE_ACK,
    BUYER_NOTE_DELIVERY_NOTE,
    BUYER_NOTE_SKIP,
    BuyerNoteCase,
    BuyerNoteReviewSelection,
    normalized_lines,
)
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.ui.modules.rechnungen.start_hold_dialog import StartHoldDialog


class BuyerNoteReviewDialog(QDialog):
    """Review every buyer note in the exact START scope before execution."""

    def __init__(
        self,
        cases: list[BuyerNoteCase],
        *,
        allow_delivery_note: bool,
        container: Container | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("START – Käufernotizen und Lieferschein")
        self.resize(940, 620)
        self._cases = list(cases)
        self._allow_delivery_note = bool(allow_delivery_note)
        self._container = container
        self._mail_worker: BackgroundWorker | None = None
        self._hold_worker: BackgroundWorker | None = None
        self._hold_saved = False
        self._hold_error: Exception | None = None
        self._selections: dict[str, BuyerNoteReviewSelection] = {}
        self._printed_cases: set[str] = set()
        self._manual_note_text = ""
        self._current_index = -1
        self._cancel: QPushButton | None = None
        self._build_ui()
        for case in self._cases:
            item = QListWidgetItem(self._item_label(case))
            item.setData(Qt.ItemDataRole.UserRole, case.invoice_id)
            self._case_list.addItem(item)
        if self._cases:
            self._case_list.setCurrentRow(0)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        split = QHBoxLayout()
        self._case_list = QListWidget()
        self._case_list.setMinimumWidth(255)
        self._case_list.setMaximumWidth(280)
        self._case_list.currentRowChanged.connect(self._show_case)
        split.addWidget(self._case_list)

        detail = QVBoxLayout()
        self._headline = QLabel()
        self._headline.setStyleSheet("font-size: 15px; font-weight: bold;")
        detail.addWidget(self._headline)
        detail.addWidget(QLabel("Käufernotiz"))
        self._note = QPlainTextEdit()
        self._note.setReadOnly(True)
        self._note.setPlaceholderText("Keine Käufernotiz")
        detail.addWidget(self._note, stretch=2)

        detail_columns = QHBoxLayout()
        address_column = QVBoxLayout()
        address_column.addWidget(QLabel("Lieferadresse"))
        self._address = QPlainTextEdit()
        self._address.setPlaceholderText("Lieferadresse fehlt")
        self._address.setMaximumHeight(145)
        address_column.addWidget(self._address)
        detail_columns.addLayout(address_column, 1)
        product_column = QVBoxLayout()
        product_column.addWidget(QLabel("Positionen"))
        self._products = QListWidget()
        self._products.setMinimumHeight(130)
        product_column.addWidget(self._products)
        detail_columns.addLayout(product_column, 2)
        detail.addLayout(detail_columns)

        split.addLayout(detail, stretch=1)
        root.addLayout(split, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._delivery = QPushButton("▤ LS")
        self._delivery.setToolTip("Lieferschein öffnen")
        self._delivery.setAccessibleName("Lieferschein öffnen")
        self._delivery.clicked.connect(self._open_delivery)
        actions.addWidget(self._delivery)
        self._mail = QPushButton("✉ MAIL")
        self._mail.setToolTip("Antwort in Outlook öffnen")
        self._mail.setAccessibleName("Kundenmail zur Käufernotiz")
        self._mail.clicked.connect(self._open_customer_mail)
        actions.addWidget(self._mail)
        self._skip = QPushButton("↷ SKIP")
        self._skip.setToolTip("Jetzt überspringen; nächster START fragt erneut")
        self._skip.setAccessibleName("Diese Rechnung überspringen")
        self._skip.clicked.connect(lambda: self._choose(BUYER_NOTE_SKIP))
        actions.addWidget(self._skip)
        self._defer = QPushButton("⏸ ZURÜCKSTELLEN")
        self._defer.setToolTip("Rechnung dauerhaft aus START nehmen")
        self._defer.clicked.connect(self._defer_current)
        actions.addWidget(self._defer)
        actions.addStretch()

        cancel = QPushButton("✕ CANCEL")
        cancel.setToolTip("START abbrechen")
        cancel.clicked.connect(self.reject)
        self._cancel = cancel
        actions.addWidget(cancel)
        self._ack = QPushButton("✓ ERLEDIGT")
        self._ack.setToolTip("Gelesen; START fortsetzen")
        self._ack.setAccessibleName("Gelesen, START fortfahren")
        self._ack.setStyleSheet("color: #22c55e; font-weight: bold")
        self._ack.clicked.connect(lambda: self._choose(BUYER_NOTE_ACK))
        actions.addWidget(self._ack)
        for button in (self._delivery, self._mail, self._skip, self._defer, cancel, self._ack):
            button.setMinimumHeight(38)
        root.addLayout(actions)

    def reject(self) -> None:
        if self._worker_in_flight():
            if self._cancel is not None:
                self._cancel.setToolTip("Aktion wird gespeichert oder ge?ffnet; bitte warten")
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker_in_flight():
            if self._cancel is not None:
                self._cancel.setToolTip("Aktion wird gespeichert oder ge?ffnet; bitte warten")
            event.ignore()
            return
        super().closeEvent(event)

    def _worker_in_flight(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in (self._mail_worker, self._hold_worker)
        )

    @staticmethod
    def _item_label(case: BuyerNoteCase) -> str:
        ref = f" · Wix {case.order_reference}" if case.order_reference else ""
        return f"{case.invoice_number or case.invoice_id}{ref}"

    def _case(self) -> BuyerNoteCase | None:
        if 0 <= self._current_index < len(self._cases):
            return self._cases[self._current_index]
        return None

    def _save_editor_values(self) -> None:
        case = self._case()
        if case is None:
            return
        current = self._selections.get(case.invoice_id)
        if current is None:
            return
        self._selections[case.invoice_id] = BuyerNoteReviewSelection(
            action=current.action,
            address_lines=normalized_lines(self._address.toPlainText().splitlines()),
            manual_note=self._manual_note_text,
        )

    def _show_case(self, index: int) -> None:
        self._save_editor_values()
        self._current_index = index
        case = self._case()
        if case is None:
            return
        self._headline.setText(f"{case.customer_name or 'Unbekannter Kunde'} · {self._item_label(case)}")
        self._note.setPlainText(case.note_text)
        selection = self._selections.get(case.invoice_id)
        self._address.setPlainText("\n".join(selection.address_lines if selection else case.address_lines))
        self._manual_note_text = selection.manual_note if selection else ""
        self._products.clear()
        for product in case.products:
            self._products.addItem(f"{product.quantity} × {product.name or product.sku or 'Produkt'}"
                                   + (f" · {product.sku}" if product.sku and product.name else ""))
        if not case.products:
            self._products.addItem("Keine Positionen verfügbar")
        is_digital = case.physical_delivery is False
        self._delivery.setEnabled(
            self._allow_delivery_note and not is_digital and self._container is not None
            and case.invoice_id not in self._printed_cases
        )
        self._mail.setEnabled(bool(case.customer_email) and self._container is not None)
        self._defer.setEnabled(self._container is not None)

    def _choose(self, action: str) -> None:
        case = self._case()
        if case is None:
            return
        address = normalized_lines(self._address.toPlainText().splitlines())
        if action == BUYER_NOTE_DELIVERY_NOTE and not address:
            QMessageBox.warning(self, "Lieferadresse fehlt", "Für den Lieferschein muss eine Lieferadresse vorhanden sein.")
            return
        self._selections[case.invoice_id] = BuyerNoteReviewSelection(
            action=action,
            address_lines=address,
            manual_note=self._manual_note_text,
        )
        item = self._case_list.item(self._current_index)
        if item is not None:
            labels = {
                BUYER_NOTE_ACK: "Gelesen",
                BUYER_NOTE_DELIVERY_NOTE: "Lieferschein",
                BUYER_NOTE_SKIP: "Übersprungen",
            }
            item.setText(f"{self._item_label(case)} · {labels.get(action, action)}")
        if len(self._selections) == len(self._cases):
            self.accept()
        else:
            next_index = next((i for i, other in enumerate(self._cases)
                               if other.invoice_id not in self._selections), -1)
            if next_index >= 0:
                self._case_list.setCurrentRow(next_index)

    def _open_delivery(self) -> None:
        case = self._case()
        if case is None or self._container is None:
            return
        address = normalized_lines(self._address.toPlainText().splitlines())
        if not address:
            QMessageBox.warning(self, "Lieferschein", "Bitte zuerst die Lieferadresse eintragen.")
            return
        if not case.products:
            QMessageBox.warning(self, "Lieferschein", "Positionen fehlen. Bitte START abbrechen und die Bestellung prüfen.")
            return
        dialog = BuyerNoteDeliveryDialog(case, address, self._manual_note_text,
                                         self._container, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._manual_note_text = dialog.manual_note
        if dialog.output == "schedule":
            self._choose(BUYER_NOTE_DELIVERY_NOTE)
        elif dialog.output == "printed":
            self._printed_cases.add(case.invoice_id)
            self._delivery.setEnabled(False)

    def _defer_current(self) -> None:
        case = self._case()
        if case is None or self._container is None:
            return
        dialog = StartHoldDialog(
            invoice_label=case.invoice_number or case.order_reference or case.invoice_id,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if self._hold_worker is not None and self._hold_worker.isRunning():
            return
        container = self._container
        reason, note, review_on = dialog.reason, dialog.note, dialog.review_on

        def job() -> object:
            service = container.resolve(InvoiceProcessingService)
            return service.defer_invoice_from_start(
                case.invoice_id, reason, note=note, review_on=review_on, expected_ready=True,
            )

        self._hold_saved = False
        self._hold_error = None
        self._set_hold_busy(True)
        worker = BackgroundWorker(job)
        worker.signals.result.connect(lambda _result: setattr(self, "_hold_saved", True))
        worker.signals.error.connect(lambda exc: setattr(self, "_hold_error", exc))
        worker.signals.finished.connect(self._hold_finished)
        self._hold_worker = worker
        worker.start()

    def _set_hold_busy(self, busy: bool) -> None:
        for widget in (
            self._case_list, self._delivery, self._mail, self._skip, self._defer,
            self._cancel, self._ack,
        ):
            if widget is not None:
                widget.setEnabled(not busy)

    def _hold_finished(self) -> None:
        self._hold_worker = None
        if self._hold_saved:
            self._set_hold_busy(False)
            self._choose(BUYER_NOTE_SKIP)
            return
        self._set_hold_busy(False)
        self._show_case(self._current_index)
        if self._hold_error is not None:
            QMessageBox.warning(self, "Rechnung zurückstellen", str(self._hold_error))

    def _open_customer_mail(self) -> None:
        case = self._case()
        if case is None or self._container is None or not case.customer_email:
            return
        container = self._container
        if self._mail_worker is not None and self._mail_worker.isRunning():
            return
        self._mail.setEnabled(False)
        quoted_note = "\n".join(f"> {line}" for line in case.note_text.splitlines())
        body = "Guten Tag,\n\n[Antwort hier eingeben]"
        original_note = f"--- Ursprüngliche Käufernotiz ---\n{quoted_note}"
        subject = f"Ihre Nachricht zu Bestellung {case.order_reference or case.invoice_number or case.invoice_id}"

        def job() -> object:
            sender = str(container.resolve(SecretService).get_secret("OUTLOOK_SENDER_EMAIL") or "")
            return open_classic_outlook_draft(
                to_email=case.customer_email,
                subject=subject,
                sender_smtp=sender,
                body=body,
                body_after_signature=original_note,
            )

        self._mail_worker = BackgroundWorker(job)
        self._mail_worker.signals.result.connect(lambda _result: QMessageBox.information(
            self, "Kundenmail", "Outlook-Entwurf geöffnet. Bitte dort prüfen und senden."
        ))
        self._mail_worker.signals.error.connect(lambda exc: QMessageBox.warning(
            self, "Kundenmail", f"Outlook-Entwurf konnte nicht geöffnet werden:\n{exc}"
        ))
        self._mail_worker.signals.finished.connect(self._mail_finished)
        self._mail_worker.start()

    def _mail_finished(self) -> None:
        self._mail_worker = None
        case = self._case()
        self._mail.setEnabled(bool(case and case.customer_email))
        if self._cancel is not None:
            self._cancel.setToolTip("START abbrechen")

    def selections(self) -> dict[str, tuple[BuyerNoteCase, BuyerNoteReviewSelection]]:
        return {
            case.invoice_id: (case, self._selections[case.invoice_id])
            for case in self._cases
            if case.invoice_id in self._selections
        }
