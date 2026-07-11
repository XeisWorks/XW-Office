"""Dialog for OFFENE SENDUNGEN workflow."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from xw_studio.core.container import Container
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.printing.label_printer import LabelPrinter
from xw_studio.services.printing.print_queue import PrintQueueService
from xw_studio.services.sendungen.service import (
    OffeneSendungenService,
    SendungCase,
    SendungExtraction,
    SendungProductLine,
)


class OffeneSendungenDialog(QDialog):
    """Sendungen workflow based on legacy Daily-Business behavior, without UI blocking."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: OffeneSendungenService = container.resolve(OffeneSendungenService)
        self._cases: list[SendungCase] = []
        self._load_worker: BackgroundWorker | None = None
        self._detail_worker: BackgroundWorker | None = None
        self._detail_workers: list[BackgroundWorker] = []
        self._action_worker: BackgroundWorker | None = None
        self._load_seq = 0
        self._detail_seq = 0
        self._delivery_pdf_by_case: dict[str, Path] = {}
        self._build_ui()
        QTimer.singleShot(0, lambda: self._load_cases(refresh=True))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._wait_for_workers()
        super().closeEvent(event)

    def accept(self) -> None:
        self._load_seq += 1
        self._detail_seq += 1
        self._wait_for_workers()
        super().accept()

    def reject(self) -> None:
        self._load_seq += 1
        self._detail_seq += 1
        self._wait_for_workers()
        super().reject()

    def _wait_for_workers(self) -> None:
        workers = [self._load_worker, self._detail_worker, self._action_worker, *self._detail_workers]
        for worker in workers:
            if worker is not None and worker.isRunning():
                worker.wait(3000)

    def _build_ui(self) -> None:
        self.setWindowTitle("OFFENE SENDUNGEN")
        self.setMinimumSize(1160, 720)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self._status = QLabel("-")
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

        self._meta = QLabel("Keine Sendung ausgewaehlt")
        self._meta.setWordWrap(True)
        right_lay.addWidget(self._meta)

        self._summary = QPlainTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setPlaceholderText("OpenAI-Zusammenfassung")
        self._summary.setMinimumHeight(95)
        right_lay.addWidget(self._summary)

        self._thread = QPlainTextEdit()
        self._thread.setReadOnly(True)
        self._thread.setPlaceholderText("Mailverlauf / Inhalt")
        self._thread.setMinimumHeight(130)
        right_lay.addWidget(self._thread)

        self._detail_status = QLabel("Quelle: -")
        self._detail_status.setWordWrap(True)
        right_lay.addWidget(self._detail_status)

        right_lay.addWidget(QLabel("Lieferadresse fuer Label (bearbeitbar, eine Zeile pro Zeile):"))
        self._address = QPlainTextEdit()
        self._address.setMinimumHeight(92)
        right_lay.addWidget(self._address)

        row_products_header = QHBoxLayout()
        row_products_header.addWidget(QLabel("Produkte fuer Lieferschein:"))
        row_products_header.addStretch(1)
        self._btn_add_product = QPushButton("Produktzeile +")
        self._btn_add_product.clicked.connect(lambda: self._add_product_row(SendungProductLine()))
        row_products_header.addWidget(self._btn_add_product)
        self._btn_remove_product = QPushButton("Produktzeile -")
        self._btn_remove_product.clicked.connect(self._remove_selected_product_row)
        row_products_header.addWidget(self._btn_remove_product)
        right_lay.addLayout(row_products_header)

        self._products = QTableWidget(0, 4)
        self._products.setHorizontalHeaderLabels(["Menge", "Produkt", "SKU", "Notiz"])
        self._products.setMinimumHeight(150)
        self._products.horizontalHeader().setStretchLastSection(True)
        self._products.setColumnWidth(0, 70)
        self._products.setColumnWidth(1, 330)
        self._products.setColumnWidth(2, 130)
        right_lay.addWidget(self._products)

        right_lay.addWidget(QLabel("Manueller Text fuer Lieferschein:"))
        self._manual_text = QPlainTextEdit()
        self._manual_text.setMinimumHeight(70)
        right_lay.addWidget(self._manual_text)

        row_actions = QHBoxLayout()
        self._btn_extract = QPushButton("OpenAI neu extrahieren")
        self._btn_extract.clicked.connect(lambda: self._extract_selected(force=True))
        row_actions.addWidget(self._btn_extract)

        self._btn_label = QPushButton("Label drucken")
        self._btn_label.clicked.connect(self._print_label)
        row_actions.addWidget(self._btn_label)

        self._btn_delivery_show = QPushButton("Lieferschein zeigen")
        self._btn_delivery_show.clicked.connect(self._show_delivery_note)
        row_actions.addWidget(self._btn_delivery_show)

        self._btn_delivery_print = QPushButton("Lieferschein drucken")
        self._btn_delivery_print.clicked.connect(self._print_delivery_note)
        row_actions.addWidget(self._btn_delivery_print)

        row_actions.addStretch(1)
        self._btn_done = QPushButton("Sendung erledigt")
        self._btn_done.clicked.connect(self._mark_done)
        row_actions.addWidget(self._btn_done)
        right_lay.addLayout(row_actions)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
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
        self._status.setText("Lade offene Sendungen...")
        self._list.setEnabled(False)
        self._list.clear()
        self._clear_detail("Lade offene Sendungen...")

        def job() -> list[SendungCase]:
            if refresh:
                self._service.refresh_from_graph(lookback_days=20, max_items=150)
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
            item = QListWidgetItem(f"{case.received_at[:16]} | {case.sender} | {case.subject}")
            item.setData(Qt.ItemDataRole.UserRole, case.id)
            self._list.addItem(item)
        self._list.setEnabled(True)
        self._status.setText(f"{len(self._cases)} offene Sendungen")
        if self._cases:
            self._list.setCurrentRow(0)
        else:
            self._clear_detail("Keine offenen Sendungen.")

    def _on_cases_load_error(self, exc: Exception) -> None:
        self._list.setEnabled(True)
        self._status.setText("Laden fehlgeschlagen")
        self._clear_detail("Offene Sendungen konnten nicht geladen werden.")
        QMessageBox.warning(self, "OFFENE SENDUNGEN", f"Laden fehlgeschlagen:\n\n{exc}")

    def _current_case(self) -> SendungCase | None:
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
                    f"Wix-Order-Nr: {case.order_number or 'nicht erkannt'}",
                    f"Conversation: {case.thread_id or '-'}",
                ]
            )
        )
        self._thread.setPlainText(case.thread_text or case.body or case.snippet)
        self._set_detail_loading("Lade OpenAI-Auswertung und gespeicherte Korrekturen...")
        self._extract_selected(force=False)

    def _extract_selected(self, *, force: bool) -> None:
        case = self._current_case()
        if case is None:
            return
        self._detail_seq += 1
        seq = self._detail_seq
        case_id = case.id
        self._set_detail_loading("Analysiere Mailverlauf..." if force else "Lade Details...")

        def job() -> tuple[str, SendungExtraction, dict[str, object]]:
            extraction = self._service.extract_case_details(case_id, force=force)
            manual = self._service.load_manual_fields(case_id)
            return case_id, extraction, manual

        worker = BackgroundWorker(job)
        self._detail_worker = worker
        self._detail_workers.append(worker)
        worker.signals.result.connect(lambda result, token=seq: self._on_detail_loaded(token, result))
        worker.signals.error.connect(lambda exc, token=seq: self._on_detail_error(token, exc))
        worker.signals.finished.connect(lambda w=worker: self._on_detail_worker_finished(w))
        worker.start()

    def _on_detail_worker_finished(self, worker: BackgroundWorker) -> None:
        if self._detail_worker is worker:
            self._detail_worker = None
        try:
            self._detail_workers.remove(worker)
        except ValueError:
            pass

    def _on_detail_loaded(self, seq: int, result: object) -> None:
        if not isValid(self):
            return
        if seq != self._detail_seq or not isinstance(result, tuple) or len(result) != 3:
            return
        case_id, extraction, manual = result
        case = self._current_case()
        if case is None or case.id != case_id or not isinstance(extraction, SendungExtraction):
            return
        self._summary.setPlainText(extraction.summary)
        if extraction.thread_text:
            self._thread.setPlainText(extraction.thread_text)
        address = extraction.address_lines
        products = extraction.products
        manual_text = ""
        if isinstance(manual, dict):
            manual_address = manual.get("address_lines")
            if isinstance(manual_address, list) and manual_address:
                address = [str(line).strip() for line in manual_address if str(line).strip()]
            manual_products = manual.get("products")
            if isinstance(manual_products, list) and manual_products:
                products = [
                    SendungProductLine(
                        quantity=str(item.get("quantity") or "1").strip(),
                        name=str(item.get("name") or "").strip(),
                        sku=str(item.get("sku") or "").strip(),
                        note=str(item.get("note") or "").strip(),
                    )
                    for item in manual_products
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                ]
            manual_text = str(manual.get("manual_text") or "").strip()
        self._address.setPlainText("\n".join(address))
        self._set_products(products)
        self._manual_text.setPlainText(manual_text)
        notes = ", ".join(extraction.confidence_notes or [])
        suffix = f" | {notes}" if notes else ""
        self._detail_status.setText(f"Quelle: {extraction.source}{suffix}")
        self._set_actions_enabled(True)

    def _on_detail_error(self, seq: int, exc: Exception) -> None:
        if not isValid(self):
            return
        if seq != self._detail_seq:
            return
        self._detail_status.setText("Quelle: Laden fehlgeschlagen")
        self._set_actions_enabled(True)
        QMessageBox.warning(self, "OFFENE SENDUNGEN", f"Details konnten nicht geladen werden:\n\n{exc}")

    def _set_detail_loading(self, message: str) -> None:
        self._summary.setPlainText("Laden...")
        self._detail_status.setText(message)
        self._address.setPlainText("")
        self._products.setRowCount(0)
        self._manual_text.setPlainText("")
        self._set_actions_enabled(False)

    def _clear_detail(self, message: str) -> None:
        self._meta.setText(message)
        self._summary.setPlainText("")
        self._thread.setPlainText("")
        self._detail_status.setText("Quelle: -")
        self._address.setPlainText("")
        self._products.setRowCount(0)
        self._manual_text.setPlainText("")
        self._set_actions_enabled(False)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in (
            self._btn_extract,
            self._btn_label,
            self._btn_delivery_show,
            self._btn_delivery_print,
            self._btn_done,
            self._btn_add_product,
            self._btn_remove_product,
        ):
            button.setEnabled(enabled)

    def _set_products(self, products: list[SendungProductLine]) -> None:
        self._products.setRowCount(0)
        for product in products:
            self._add_product_row(product)
        if not products:
            self._add_product_row(SendungProductLine())

    def _add_product_row(self, product: SendungProductLine) -> None:
        row = self._products.rowCount()
        self._products.insertRow(row)
        values = [product.quantity, product.name, product.sku, product.note]
        for col, value in enumerate(values):
            self._products.setItem(row, col, QTableWidgetItem(str(value or "")))

    def _remove_selected_product_row(self) -> None:
        row = self._products.currentRow()
        if row >= 0:
            self._products.removeRow(row)

    def _address_lines(self) -> list[str]:
        return [line.strip() for line in self._address.toPlainText().splitlines() if line.strip()]

    def _products_from_table(self) -> list[SendungProductLine]:
        products: list[SendungProductLine] = []
        for row in range(self._products.rowCount()):
            quantity = self._cell_text(row, 0) or "1"
            name = self._cell_text(row, 1)
            sku = self._cell_text(row, 2)
            note = self._cell_text(row, 3)
            if name:
                products.append(SendungProductLine(quantity=quantity, name=name, sku=sku, note=note))
        return products

    def _cell_text(self, row: int, column: int) -> str:
        item = self._products.item(row, column)
        return item.text().strip() if item is not None else ""

    def _save_current_manual_fields(self) -> None:
        case = self._current_case()
        if case is None:
            return
        self._service.save_manual_fields(
            case.id,
            address_lines=self._address_lines(),
            products=self._products_from_table(),
            manual_text=self._manual_text.toPlainText(),
        )

    def _print_label(self) -> None:
        case = self._current_case()
        if case is None:
            return
        lines = self._address_lines()
        if not lines:
            QMessageBox.information(self, "Label", "Keine Adresszeilen vorhanden.")
            return
        case_id = case.id
        products = self._products_from_table()
        manual_text = self._manual_text.toPlainText()

        def job() -> bool:
            self._service.save_manual_fields(
                case_id,
                address_lines=lines,
                products=products,
                manual_text=manual_text,
            )
            printer = LabelPrinter(
                self._container.config.printing,
                print_queue=self._container.resolve(PrintQueueService),
            )
            printer.print_address(lines)
            return True

        self._start_action(
            self._btn_label,
            "Drucke...",
            job,
            self._on_label_printed,
        )

    def _on_label_printed(self, _payload: object) -> None:
        QMessageBox.information(self, "Label", "Label erfolgreich an Drucker gesendet.")

    def _create_delivery_note(self) -> Path:
        case = self._current_case()
        if case is None:
            raise RuntimeError("Keine Sendung ausgewaehlt")
        path = self._service.generate_delivery_note_pdf(
            case.id,
            address_lines=self._address_lines(),
            products=self._products_from_table(),
            manual_text=self._manual_text.toPlainText(),
            summary=self._summary.toPlainText(),
        )
        self._delivery_pdf_by_case[case.id] = path
        return path

    def _show_delivery_note(self) -> None:
        request = self._delivery_note_request()
        if request is None:
            return
        case_id, address, products, manual_text, summary = request

        def job() -> Path:
            return self._service.generate_delivery_note_pdf(
                case_id,
                address_lines=address,
                products=products,
                manual_text=manual_text,
                summary=summary,
            )

        self._start_action(
            self._btn_delivery_show,
            "Erstelle...",
            job,
            self._on_delivery_note_ready,
        )

    @staticmethod
    def _on_delivery_note_ready(payload: object) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(payload)))

    def _print_delivery_note(self) -> None:
        request = self._delivery_note_request()
        if request is None:
            return
        case_id, address, products, manual_text, summary = request

        def job() -> Path:
            path = self._service.generate_delivery_note_pdf(
                case_id,
                address_lines=address,
                products=products,
                manual_text=manual_text,
                summary=summary,
            )
            self._service.print_delivery_note(
                path,
                printing=self._container.config.printing,
                print_queue=self._container.resolve(PrintQueueService),
            )
            return path

        self._start_action(
            self._btn_delivery_print,
            "Drucke...",
            job,
            self._on_delivery_note_printed,
        )

    def _on_delivery_note_printed(self, _payload: object) -> None:
        QMessageBox.information(
            self, "Lieferschein", "Lieferschein erfolgreich an Rechnungen gesendet."
        )

    def _delivery_note_request(
        self,
    ) -> tuple[str, list[str], list[SendungProductLine], str, str] | None:
        case = self._current_case()
        if case is None:
            return None
        return (
            case.id,
            self._address_lines(),
            self._products_from_table(),
            self._manual_text.toPlainText(),
            self._summary.toPlainText(),
        )

    def _mark_done(self) -> None:
        case = self._current_case()
        if case is None:
            return
        case_id = case.id
        address = self._address_lines()
        products = self._products_from_table()
        manual_text = self._manual_text.toPlainText()

        def job() -> bool:
            self._service.save_manual_fields(
                case_id,
                address_lines=address,
                products=products,
                manual_text=manual_text,
            )
            self._service.mark_done(case_id, done=True)
            return True

        self._start_action(
            self._btn_done,
            "Erledige...",
            job,
            lambda _payload: self._load_cases(refresh=False),
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
        self._detail_status.setText(busy_text)
        self._action_worker = BackgroundWorker(job)
        worker = self._action_worker
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(
            lambda exc: QMessageBox.warning(self, "Aktion fehlgeschlagen", str(exc))
        )
        worker.signals.finished.connect(
            lambda current=worker, target=button, text=idle_text: self._finish_action(
                current, target, text
            )
        )
        worker.start()

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
