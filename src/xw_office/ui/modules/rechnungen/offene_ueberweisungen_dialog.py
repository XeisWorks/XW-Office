from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from xw_office.core.container import Container
from xw_office.core.worker import BackgroundWorker
from xw_office.services.transfers.models import TransferCase, TransferFieldSource, TransferPaymentData
from xw_office.services.transfers.payment_qr import PaymentQrError
from xw_office.services.transfers.service import OffeneUeberweisungenService
from xw_office.ui.modules.rechnungen.payment_qr_dialog import PaymentQrDialog


class OffeneUeberweisungenDialog(QDialog):
    """Dialog workflow for open transfer mails in dedicated transfer mailbox."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: OffeneUeberweisungenService = container.resolve(OffeneUeberweisungenService)
        self._cases: list[TransferCase] = []
        self._selected_attachment_id: str | None = None
        self._load_worker: BackgroundWorker | None = None
        self._detail_worker: BackgroundWorker | None = None
        self._detail_workers: list[BackgroundWorker] = []
        self._action_worker: BackgroundWorker | None = None
        self._load_seq = 0
        self._detail_seq = 0
        self._build_ui()
        QTimer.singleShot(0, lambda: self._load_cases(refresh=True))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._wait_for_workers()
        super().closeEvent(event)

    def accept(self) -> None:
        self._detail_seq += 1
        self._load_seq += 1
        self._wait_for_workers()
        super().accept()

    def reject(self) -> None:
        self._detail_seq += 1
        self._load_seq += 1
        self._wait_for_workers()
        super().reject()

    def _wait_for_workers(self) -> None:
        workers = [self._load_worker, self._detail_worker, self._action_worker, *self._detail_workers]
        for worker in workers:
            if worker is not None and worker.isRunning():
                worker.wait(3000)

    def _build_ui(self) -> None:
        self.setWindowTitle("OFFENE UEBERWEISUNGEN")
        self.setMinimumSize(1120, 680)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self._status = QLabel("—")
        top.addWidget(self._status, stretch=1)

        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(lambda: self._load_cases(refresh=True))
        top.addWidget(self._btn_refresh)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_case_selected)
        left_lay.addWidget(self._list)
        splitter.addWidget(left)

        right = QWidget()
        right_lay = QVBoxLayout(right)

        self._meta = QLabel("Keine Ueberweisung ausgewaehlt")
        self._meta.setWordWrap(True)
        right_lay.addWidget(self._meta)

        self._summary = QPlainTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setPlaceholderText("Zusammenfassung")
        self._summary.setMinimumHeight(120)
        right_lay.addWidget(self._summary)

        self._thread = QPlainTextEdit()
        self._thread.setReadOnly(True)
        self._thread.setPlaceholderText("Mailverlauf")
        self._thread.setMinimumHeight(170)
        right_lay.addWidget(self._thread)

        form = QFormLayout()
        self._recipient = QLineEdit()
        self._iban = QLineEdit()
        self._bic = QLineEdit()
        self._amount = QLineEdit()
        self._currency = QLineEdit("EUR")
        self._currency.setReadOnly(True)
        self._remittance = QLineEdit()
        self._invoice_number = QLineEdit()
        self._due_date = QLineEdit()
        self._note = QLineEdit()

        form.addRow("Empfaenger:", self._recipient)
        form.addRow("IBAN:", self._iban)
        form.addRow("BIC:", self._bic)
        form.addRow("Betrag:", self._amount)
        form.addRow("Waehrung:", self._currency)
        form.addRow("Zahlungsreferenz:", self._remittance)
        form.addRow("Rechnungsnummer:", self._invoice_number)
        form.addRow("Faelligkeit:", self._due_date)
        form.addRow("Notiz:", self._note)
        right_lay.addLayout(form)

        self._source_label = QLabel("Quelle: -")
        right_lay.addWidget(self._source_label)

        row_summary = QHBoxLayout()
        self._btn_summary = QPushButton("Mit OpenAI zusammenfassen")
        self._btn_summary.clicked.connect(self._summarize_selected)
        row_summary.addWidget(self._btn_summary)
        row_summary.addStretch(1)
        right_lay.addLayout(row_summary)

        row_actions = QHBoxLayout()
        self._btn_show_invoice = QPushButton("Rechnung zeigen")
        self._btn_show_invoice.clicked.connect(self._show_invoice)
        row_actions.addWidget(self._btn_show_invoice)

        self._btn_generate_qr = QPushButton("QR-Code generieren")
        self._btn_generate_qr.clicked.connect(self._generate_qr)
        row_actions.addWidget(self._btn_generate_qr)

        self._btn_defer = QPushButton("Spaeter - Alarm bleibt")
        self._btn_defer.clicked.connect(self._defer)
        row_actions.addWidget(self._btn_defer)

        self._btn_done = QPushButton("Ueberweisung durchgefuehrt")
        self._btn_done.clicked.connect(self._mark_done)
        row_actions.addWidget(self._btn_done)

        right_lay.addLayout(row_actions)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def open_count(self) -> int:
        return self._service.open_count()

    def _load_cases(self, *, refresh: bool) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self._load_seq += 1
        self._detail_seq += 1
        seq = self._load_seq
        self._status.setText("Lade offene Ueberweisungen...")
        self._list.setEnabled(False)
        self._list.clear()
        self._clear_detail("Lade offene Ueberweisungen...")

        def job() -> list[TransferCase]:
            if refresh:
                self._service.refresh_from_graph(lookback_days=60, max_items=180)
            return self._service.load_open_cases()

        self._load_worker = BackgroundWorker(job)
        self._load_worker.signals.result.connect(lambda result, token=seq: self._on_cases_loaded(token, result))
        self._load_worker.signals.error.connect(self._on_cases_load_error)
        self._load_worker.signals.finished.connect(lambda: setattr(self, "_load_worker", None))
        self._load_worker.start()

    def _on_cases_loaded(self, seq: int, result: object) -> None:
        if not isValid(self):
            return
        if seq != self._load_seq:
            return
        self._cases = list(result) if isinstance(result, list) else []
        self._list.clear()
        for case in self._cases:
            marker = ""
            if case.deferred_at:
                marker = f" [{case.defer_count}x verschoben]"
            item = QListWidgetItem(f"{case.received_at[:16]} | {case.sender} | {case.subject}{marker}")
            item.setData(Qt.ItemDataRole.UserRole, case.id)
            self._list.addItem(item)
        self._list.setEnabled(True)
        self._status.setText(f"{len(self._cases)} offene Ueberweisungen")
        if self._cases:
            self._list.setCurrentRow(0)
        else:
            self._clear_detail("Keine offenen Ueberweisungen.")

    def _on_cases_load_error(self, exc: Exception) -> None:
        self._list.setEnabled(True)
        self._status.setText("Laden fehlgeschlagen")
        self._clear_detail("Offene Ueberweisungen konnten nicht geladen werden.")
        QMessageBox.warning(self, "OFFENE UEBERWEISUNGEN", f"Laden fehlgeschlagen:\n\n{exc}")

    def _clear_detail(self, message: str) -> None:
        self._meta.setText(message)
        self._summary.setPlainText("")
        self._thread.setPlainText("")
        self._recipient.setText("")
        self._iban.setText("")
        self._bic.setText("")
        self._amount.setText("")
        self._remittance.setText("")
        self._invoice_number.setText("")
        self._due_date.setText("")
        self._note.setText("")
        self._source_label.setText("Quelle: -")

    def _set_payment_loading(self, message: str) -> None:
        self._recipient.setText("")
        self._iban.setText("")
        self._bic.setText("")
        self._amount.setText("")
        self._remittance.setText("")
        self._invoice_number.setText("")
        self._due_date.setText("")
        self._note.setText("")
        self._source_label.setText(message)
        self._btn_show_invoice.setEnabled(False)
        self._btn_generate_qr.setEnabled(False)
        self._btn_done.setEnabled(False)

    def _set_payment_actions_enabled(self, enabled: bool, *, has_attachment: bool) -> None:
        self._btn_show_invoice.setEnabled(enabled and has_attachment)
        self._btn_generate_qr.setEnabled(enabled)
        self._btn_done.setEnabled(enabled)

    def _current_case(self) -> TransferCase | None:
        idx = self._list.currentRow()
        if idx < 0 or idx >= len(self._cases):
            return None
        return self._cases[idx]

    def _on_case_selected(self, _row: int) -> None:
        case = self._current_case()
        if case is None:
            return

        self._meta.setText(
            "\n".join(
                [
                    f"Von: {case.sender}",
                    f"Betreff: {case.subject}",
                    f"Empfangen: {case.received_at}",
                    f"Conversation: {case.conversation_id or '-'}",
                ]
            )
        )
        self._thread.setPlainText(case.thread_text or case.body or case.snippet)
        self._summary.setPlainText("")
        self._set_payment_loading("Quelle: Lade Anhaenge und Zahlungsdaten...")

        self._detail_seq += 1
        seq = self._detail_seq
        case_id = case.id

        def job() -> tuple[str, list[object], TransferPaymentData]:
            attachments = self._service.list_pdf_attachments(case_id)
            attachment_id = attachments[0].id if attachments else None
            payment = self._service.extract_payment_data(case_id, attachment_id=attachment_id)
            return case_id, list(attachments), payment

        self._detail_worker = BackgroundWorker(job)
        worker = self._detail_worker
        self._detail_workers.append(worker)
        worker.signals.result.connect(lambda result, token=seq: self._on_case_detail_loaded(token, result))
        worker.signals.error.connect(lambda exc, token=seq: self._on_case_detail_error(token, exc))
        worker.signals.finished.connect(lambda w=worker: self._on_detail_worker_finished(w))
        worker.start()

    def _on_detail_worker_finished(self, worker: BackgroundWorker) -> None:
        if self._detail_worker is worker:
            self._detail_worker = None
        try:
            self._detail_workers.remove(worker)
        except ValueError:
            pass

    def _on_case_detail_loaded(self, seq: int, result: object) -> None:
        if not isValid(self):
            return
        if seq != self._detail_seq or not isinstance(result, tuple) or len(result) != 3:
            return
        case_id, attachments, payment = result
        case = self._current_case()
        if case is None or case.id != case_id or not isinstance(payment, TransferPaymentData):
            return
        self._selected_attachment_id = attachments[0].id if attachments else None
        self._fill_payment_form(payment)
        self._set_payment_actions_enabled(True, has_attachment=bool(attachments))

    def _on_case_detail_error(self, seq: int, exc: Exception) -> None:
        if not isValid(self):
            return
        if seq != self._detail_seq:
            return
        self._selected_attachment_id = None
        self._set_payment_actions_enabled(True, has_attachment=False)
        self._source_label.setText("Quelle: Laden fehlgeschlagen")
        QMessageBox.warning(self, "OFFENE UEBERWEISUNGEN", f"Zahlungsdaten konnten nicht geladen werden:\n\n{exc}")

    def _fill_payment_form(self, payment: TransferPaymentData) -> None:
        self._recipient.setText(payment.recipient)
        self._iban.setText(payment.iban)
        self._bic.setText(payment.bic)
        self._amount.setText(str(payment.amount or ""))
        self._remittance.setText(payment.remittance_text)
        self._invoice_number.setText(payment.invoice_number)
        self._due_date.setText(payment.due_date)
        self._note.setText(payment.note)
        sources: list[str] = []
        for field_name in ("recipient", "iban", "bic", "amount", "remittance_text", "invoice_number"):
            source = payment.source_by_field.get(field_name, TransferFieldSource.UNKNOWN)
            sources.append(f"{field_name}:{source.value}")
        self._source_label.setText(f"Quelle: {' | '.join(sources)}")

    def _collect_payment_form(self) -> TransferPaymentData:
        amount_raw = self._amount.text().strip()
        amount: Decimal | None = None
        if amount_raw:
            normalized = amount_raw.replace(" ", "")
            if "," in normalized and "." in normalized:
                if normalized.rfind(",") > normalized.rfind("."):
                    normalized = normalized.replace(".", "").replace(",", ".")
                else:
                    normalized = normalized.replace(",", "")
            else:
                normalized = normalized.replace(",", ".")
            try:
                amount = Decimal(normalized)
            except InvalidOperation:
                amount = None

        return TransferPaymentData(
            recipient=self._recipient.text().strip(),
            iban=self._iban.text().strip(),
            bic=self._bic.text().strip(),
            amount=amount,
            currency="EUR",
            remittance_text=self._remittance.text().strip(),
            invoice_number=self._invoice_number.text().strip(),
            due_date=self._due_date.text().strip(),
            note=self._note.text().strip(),
            source_by_field={
                "recipient": TransferFieldSource.MANUAL,
                "iban": TransferFieldSource.MANUAL,
                "bic": TransferFieldSource.MANUAL,
                "amount": TransferFieldSource.MANUAL,
                "remittance_text": TransferFieldSource.MANUAL,
                "invoice_number": TransferFieldSource.MANUAL,
            },
        )

    def _summarize_selected(self) -> None:
        case = self._current_case()
        if case is None:
            return
        case_id = case.id

        def job() -> str:
            return self._service.summarize_case(case_id)

        self._start_action(
            self._btn_summary,
            "Zusammenfassen...",
            job,
            lambda payload: self._summary.setPlainText(str(payload)),
        )

    def _show_invoice(self) -> None:
        case = self._current_case()
        if case is None:
            return
        attachments = self._service.list_pdf_attachments(case.id)
        if not attachments:
            QMessageBox.information(self, "Rechnung", "Keine PDF-Rechnung in dieser Mail gefunden.")
            return
        chosen = attachments[0]
        if len(attachments) > 1:
            labels = [f"{att.name} ({att.size or 0} Bytes)" for att in attachments]
            selected_label, ok = QInputDialog.getItem(self, "PDF auswaehlen", "Anhang:", labels, 0, False)
            if not ok:
                return
            chosen = attachments[labels.index(selected_label)]

        data = self._service.download_attachment_bytes(case.id, chosen.id)
        temp_path = Path(__file__).resolve().parents[5] / "state" / "tmp" / f"transfer_{case.id}_{chosen.name}"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(data)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(temp_path))):
            QMessageBox.warning(self, "Rechnung", "PDF konnte nicht geoeffnet werden.")

    def _generate_qr(self) -> None:
        case = self._current_case()
        if case is None:
            return
        payment = self._collect_payment_form()
        case_id = case.id

        def job() -> tuple[Path, TransferPaymentData]:
            self._service.save_manual_payment(case_id, payment)
            return self._service.generate_qr(case_id, payment), payment

        self._start_action(self._btn_generate_qr, "QR wird erstellt...", job, self._on_qr_generated)

    def _on_qr_generated(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        qr_path, payment = payload
        if not isinstance(qr_path, Path) or not isinstance(payment, TransferPaymentData):
            return
        PaymentQrDialog(qr_path, payment, self).exec()

    def _defer(self) -> None:
        case = self._current_case()
        if case is None:
            self.reject()
            return
        case_id = case.id
        note = self._note.text().strip()

        def job() -> bool:
            self._service.mark_deferred(case_id, note=note)
            return True

        self._start_action(
            self._btn_defer,
            "Verschiebe...",
            job,
            lambda _payload: QTimer.singleShot(0, self.accept),
        )

    def _mark_done(self) -> None:
        case = self._current_case()
        if case is None:
            return
        choice = QMessageBox.question(
            self,
            "Ueberweisung durchgefuehrt",
            "Diese Ueberweisung als durchgefuehrt markieren?\n"
            "Die Mail wird in Outlook als erledigt markiert.\n"
            "Der Alarm verschwindet danach fuer diesen Fall.",
        )
        if choice != QMessageBox.StandardButton.Yes:
            return

        payment = self._collect_payment_form()
        case_id = case.id
        note = self._note.text().strip()

        def job() -> bool:
            self._service.save_manual_payment(case_id, payment)
            self._service.mark_done_in_outlook(
                case_id,
                payment,
                qr_path="",
                note=note,
            )
            return True

        self._start_action(
            self._btn_done,
            "Erledige...",
            job,
            lambda _payload: self._load_cases(refresh=True),
        )

    def _start_action(
        self,
        button: QPushButton,
        busy_text: str,
        job: Callable[[], Any],
        on_result: Callable[[object], None],
    ) -> None:
        if self._action_worker is not None and self._action_worker.isRunning():
            return
        idle_text = button.text()
        button.setEnabled(False)
        button.setText(busy_text)
        self._detail_status_for_action(busy_text)
        self._action_worker = BackgroundWorker(job)
        worker = self._action_worker
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self._on_action_error)
        worker.signals.finished.connect(
            lambda current=worker, target=button, text=idle_text: self._finish_action(
                current, target, text
            )
        )
        worker.start()

    def _detail_status_for_action(self, text: str) -> None:
        self._source_label.setText(text)

    def _on_action_error(self, exc: Exception) -> None:
        title = "QR-Code" if isinstance(exc, PaymentQrError) else "Aktion fehlgeschlagen"
        QMessageBox.warning(self, title, str(exc))

    def _finish_action(
        self,
        worker: BackgroundWorker,
        button: QPushButton,
        idle_text: str,
    ) -> None:
        if self._action_worker is worker:
            self._action_worker = None
        button.setEnabled(True)
        button.setText(idle_text)
