"""Dialog for OFFENE SENDUNGEN workflow."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from xw_office.core.container import Container
from xw_office.core.worker import BackgroundWorker
from xw_office.services.printing.label_printer import LabelPrinter
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.sendungen.service import (
    OffeneSendungenService,
    SendungCase,
    SendungExtraction,
    SendungProductLine,
)


class _SendungProductsModel(QAbstractTableModel):
    _headers = ["Anz.", "Produkt", "SKU", "Notiz", "Gratis", "Preis (€)", "Keine Retoure"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[SendungProductLine] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if index.column() in (4, 6) and role == Qt.ItemDataRole.CheckStateRole:
            checked = row.free_delivery if index.column() == 4 else row.no_return_required
            return Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        values = [row.quantity, row.name, row.sku, row.note, "", row.delivery_price, ""]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return values[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (0, 4, 5, 6):
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def setData(self, index: QModelIndex, value: object, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return False
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() in (4, 6):
            checked = value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value
            if index.column() == 4:
                self._rows[index.row()] = replace(row, free_delivery=checked)
                right = self.index(index.row(), 5)
                self.dataChanged.emit(index, right, [role, Qt.ItemDataRole.DisplayRole])
            else:
                self._rows[index.row()] = replace(row, no_return_required=checked)
                self.dataChanged.emit(index, index, [role])
            return True
        if role != Qt.ItemDataRole.EditRole or index.column() in (4, 6):
            return False
        values = [row.quantity, row.name, row.sku, row.note]
        if index.column() <= 3:
            values[index.column()] = str(value or "").strip()
            self._rows[index.row()] = replace(
                row,
                quantity=values[0] or "1",
                name=values[1],
                sku=values[2],
                note=values[3],
            )
        elif index.column() == 5 and not row.free_delivery:
            self._rows[index.row()] = replace(row, delivery_price=str(value or "").strip())
        else:
            return False
        self.dataChanged.emit(index, index, [role])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() in (4, 6):
            return base | Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == 5 and self._rows[index.row()].free_delivery:
            return base
        return base | Qt.ItemFlag.ItemIsEditable

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._headers[section]
        return None

    def set_products(self, rows: list[SendungProductLine]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def add_product(self, product: SendungProductLine) -> None:
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append(product)
        self.endInsertRows()

    def remove_row(self, row: int) -> None:
        if not (0 <= row < len(self._rows)):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._rows[row]
        self.endRemoveRows()

    def products(self) -> list[SendungProductLine]:
        return [row for row in self._rows if str(row.name or "").strip()]


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
        self._recipient_names: dict[str, str] = {}
        self._silent_refresh_scheduled = False
        self._silent_refresh_timer = QTimer(self)
        self._silent_refresh_timer.setSingleShot(True)
        self._silent_refresh_timer.timeout.connect(
            lambda: self._load_cases(refresh=True, preserve=True, silent=True)
        )
        self._products_model = _SendungProductsModel(self)
        self._build_ui()
        QTimer.singleShot(0, lambda: self._load_cases(refresh=False))

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
        self.setMinimumSize(1100, 700)
        self.resize(1500, 920)

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self._status = QLabel("-")
        top.addWidget(self._status, stretch=1)
        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(
            lambda: self._load_cases(refresh=True, preserve=True)
        )
        top.addWidget(self._btn_refresh)
        self._btn_extract = QPushButton("OpenAI neu extrahieren")
        self._btn_extract.clicked.connect(lambda: self._extract_selected(force=True))
        top.addWidget(self._btn_extract)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left.setMinimumWidth(310)
        left_lay = QVBoxLayout(left)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_case_selected)
        left_lay.addWidget(self._list)
        splitter.addWidget(left)

        right_panel = QWidget()
        right_outer_lay = QVBoxLayout(right_panel)
        right_outer_lay.setContentsMargins(0, 0, 0, 0)
        right_outer_lay.setSpacing(8)
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QFrame.Shape.NoFrame)
        right.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_content = QWidget()
        right_lay = QVBoxLayout(right_content)
        right_lay.setContentsMargins(10, 0, 10, 0)
        right_lay.setSpacing(7)
        right.setWidget(right_content)
        right_outer_lay.addWidget(right, stretch=1)

        self._summary = QLabel("Keine Sendung ausgewählt")
        self._summary.setWordWrap(True)
        self._summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._summary.setStyleSheet(
            "font-size: 16px; font-weight: 600; padding: 2px 0 5px 0;"
        )
        right_lay.addWidget(self._summary)

        self._meta = QLabel("")
        self._meta.setWordWrap(True)
        self._meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._meta.setStyleSheet("font-size: 10px; color: #94a3b8;")
        right_lay.addWidget(self._meta)

        self._thread = QPlainTextEdit()
        self._thread.setReadOnly(True)
        self._thread.setPlaceholderText("Mailverlauf / Inhalt")
        self._thread.setMinimumHeight(250)
        self._thread.setMaximumHeight(420)
        right_lay.addWidget(self._thread)

        self._detail_status = QLabel("Quelle: -")
        self._detail_status.setWordWrap(True)
        self._detail_status.setStyleSheet("font-size: 10px; color: #94a3b8;")
        right_lay.addWidget(self._detail_status)

        detail_columns = QSplitter(Qt.Orientation.Horizontal)
        products_panel = QWidget()
        products_lay = QVBoxLayout(products_panel)
        products_lay.setContentsMargins(0, 0, 8, 0)
        products_lay.setSpacing(6)
        products_lay.addWidget(QLabel("PRODUKTE"))

        self._products = QTableView()
        self._products.setModel(self._products_model)
        self._products.setMinimumHeight(190)
        self._products.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for column, width in enumerate((45, 190, 75, 120, 55, 70, 95)):
            self._products.setColumnWidth(column, width)
        products_lay.addWidget(self._products)

        product_row = QHBoxLayout()
        self._btn_add_product = QPushButton("+ Produkt")
        self._btn_add_product.clicked.connect(
            lambda: self._add_product_row(SendungProductLine())
        )
        product_row.addWidget(self._btn_add_product)
        self._btn_remove_product = QPushButton("− Produkt")
        self._btn_remove_product.clicked.connect(self._remove_selected_product_row)
        product_row.addWidget(self._btn_remove_product)
        product_row.addStretch(1)
        products_lay.addLayout(product_row)

        products_lay.addWidget(QLabel("Zusatztext Lieferschein:"))
        self._manual_text = QPlainTextEdit()
        self._manual_text.setMinimumHeight(58)
        self._manual_text.setMaximumHeight(85)
        products_lay.addWidget(self._manual_text)

        delivery_row = QHBoxLayout()
        self._btn_delivery_show = QPushButton("Lieferschein zeigen")
        self._btn_delivery_show.clicked.connect(self._show_delivery_note)
        delivery_row.addWidget(self._btn_delivery_show)
        self._btn_delivery_print = QPushButton("Lieferschein drucken")
        self._btn_delivery_print.clicked.connect(self._print_delivery_note)
        delivery_row.addWidget(self._btn_delivery_print)
        delivery_row.addStretch(1)
        products_lay.addLayout(delivery_row)
        detail_columns.addWidget(products_panel)

        address_panel = QWidget()
        address_lay = QVBoxLayout(address_panel)
        address_lay.setContentsMargins(8, 0, 0, 0)
        address_lay.setSpacing(6)
        address_lay.addWidget(QLabel("LIEFERANSCHRIFT"))
        self._address = QPlainTextEdit()
        self._address.setPlaceholderText("Eine Adresszeile pro Zeile")
        self._address.setMinimumHeight(190)
        address_lay.addWidget(self._address)
        address_actions = QHBoxLayout()
        self._btn_label = QPushButton("Label drucken")
        self._btn_label.clicked.connect(self._print_label)
        address_actions.addWidget(self._btn_label)
        address_actions.addStretch(1)
        address_lay.addLayout(address_actions)
        detail_columns.addWidget(address_panel)
        detail_columns.setStretchFactor(0, 3)
        detail_columns.setStretchFactor(1, 2)
        detail_columns.setSizes([650, 420])
        right_lay.addWidget(detail_columns)

        done_row = QHBoxLayout()
        done_row.addStretch(1)
        self._btn_done = QPushButton("✓")
        self._btn_done.setToolTip("Sendung erledigt")
        self._btn_done.setAccessibleName("Sendung erledigt")
        self._btn_done.setFixedSize(58, 48)
        self._btn_done.setStyleSheet(
            "QPushButton { background-color: #16803c; color: white; border-radius: 8px;"
            " font-size: 28px; font-weight: bold; }"
            "QPushButton:hover { background-color: #16a34a; }"
            "QPushButton:disabled { background-color: #64748b; }"
        )
        self._btn_done.clicked.connect(self._mark_done)
        done_row.addWidget(self._btn_done)
        right_outer_lay.addLayout(done_row)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([340, 1160])
        root.addWidget(splitter)

    def open_count(self) -> int:
        return self._service.open_count()

    def _load_cases(
        self,
        *,
        refresh: bool,
        preserve: bool = False,
        silent: bool = False,
    ) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self._load_seq += 1
        # A preserving refresh is intentionally allowed to run alongside the
        # selected case's detail extraction.  The initial cache-only load is
        # followed by a silent Graph refresh after 600 ms; invalidating the
        # detail sequence here made every extraction taking longer than that
        # appear to be stuck at "Laden..." forever.
        if not preserve:
            self._invalidate_detail_load()
        seq = self._load_seq
        selected = self._current_case()
        selected_id = selected.id if preserve and selected is not None else ""
        self._status.setText(
            "Aktualisiere offene Sendungen..." if preserve else "Lade offene Sendungen..."
        )
        if not preserve:
            self._list.setEnabled(False)
            self._list.clear()
            self._clear_detail("Lade offene Sendungen...")

        def job() -> tuple[list[SendungCase], dict[str, str]]:
            if refresh:
                self._service.refresh_from_graph(
                    lookback_days=20,
                    max_items=150,
                    allow_interactive_auth=not silent,
                )
            cases = self._service.load_open_cases()
            names_loader = getattr(self._service, "load_cached_recipient_names", None)
            names = names_loader(cases) if callable(names_loader) else {}
            return cases, names if isinstance(names, dict) else {}

        self._load_worker = BackgroundWorker(job)
        self._load_worker.signals.result.connect(
            lambda result, token=seq, keep=preserve, cid=selected_id: self._on_cases_loaded(
                token, result, preserve=keep, selected_id=cid
            )
        )
        self._load_worker.signals.error.connect(self._on_cases_load_error)
        self._load_worker.signals.finished.connect(lambda: setattr(self, "_load_worker", None))
        self._load_worker.start()

    def _on_cases_loaded(
        self,
        seq: int,
        result: object,
        *,
        preserve: bool = False,
        selected_id: str = "",
    ) -> None:
        if not isValid(self):
            return
        if seq != self._load_seq:
            return
        if isinstance(result, tuple) and len(result) == 2:
            cases, names = result
        else:
            cases, names = result, {}
        self._cases = list(cases) if isinstance(cases, list) else []
        self._recipient_names = dict(names) if isinstance(names, dict) else {}
        self._list.blockSignals(True)
        self._list.clear()
        selected_row = 0
        for row, case in enumerate(self._cases):
            item = QListWidgetItem(self._case_list_text(case))
            item.setData(Qt.ItemDataRole.UserRole, case.id)
            self._list.addItem(item)
            if selected_id and case.id == selected_id:
                selected_row = row
        self._list.setEnabled(True)
        self._status.setText(f"{len(self._cases)} offene Sendungen")
        if self._cases:
            self._list.setCurrentRow(selected_row)
        else:
            self._clear_detail("Keine offenen Sendungen.")
        self._list.blockSignals(False)
        selection_preserved = bool(
            preserve
            and selected_id
            and self._cases
            and self._cases[selected_row].id == selected_id
        )
        if self._cases and not selection_preserved:
            self._on_case_selected(selected_row)
        if not preserve and not self._silent_refresh_scheduled:
            self._silent_refresh_scheduled = True
            self._silent_refresh_timer.start(600)

    def _case_list_text(self, case: SendungCase, *, recipient_name: str = "") -> str:
        raw_date = str(case.received_at or "").strip()
        short_date = raw_date[:10]
        try:
            short_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).strftime("%d.%m.")
        except ValueError:
            if len(raw_date) >= 10:
                short_date = f"{raw_date[8:10]}.{raw_date[5:7]}."
        display_name = (
            str(recipient_name or "").strip()
            or self._recipient_names.get(case.id, "").strip()
            or str(case.sender_name or "").strip()
            or str(case.sender or "").strip()
            or "Unbekannt"
        )
        return f"{short_date} {display_name}"

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
        self._thread.setPlainText(self._compact_thread_text(case.thread_text or case.body or case.snippet))
        self._set_detail_loading("Lade OpenAI-Auswertung und gespeicherte Korrekturen...")
        self._extract_selected(force=False)

    def _extract_selected(self, *, force: bool) -> None:
        case = self._current_case()
        if case is None:
            return
        self._invalidate_detail_load()
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

    def _invalidate_detail_load(self) -> None:
        """Ignore obsolete detail results and stop publishing redundant work."""
        self._detail_seq += 1
        worker = self._detail_worker
        if worker is not None and worker.isRunning():
            worker.cancel()

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
        self._summary.setText(extraction.summary)
        if extraction.thread_text:
            self._thread.setPlainText(self._compact_thread_text(extraction.thread_text))
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
                        free_delivery=self._manual_bool(item.get("free_delivery"), default=True),
                        delivery_price=str(item.get("delivery_price") or "5,90").strip() or "5,90",
                        no_return_required=self._manual_bool(item.get("no_return_required"), default=True),
                    )
                    for item in manual_products
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                ]
            manual_text = str(manual.get("manual_text") or "").strip()
        self._address.setPlainText("\n".join(address))
        if address:
            row = self._list.currentRow()
            item = self._list.item(row)
            case = self._current_case()
            if item is not None and case is not None:
                recipient_name = str(address[0] or "").strip()
                self._recipient_names[case.id] = recipient_name
                item.setText(self._case_list_text(case, recipient_name=recipient_name))
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
        self._summary.setText("Laden...")
        self._detail_status.setText(message)
        self._address.setPlainText("")
        self._products_model.set_products([])
        self._manual_text.setPlainText("")
        self._set_actions_enabled(False)

    def _clear_detail(self, message: str) -> None:
        self._summary.setText(message)
        self._meta.setText("")
        self._thread.setPlainText("")
        self._detail_status.setText("Quelle: -")
        self._address.setPlainText("")
        self._products_model.set_products([])
        self._manual_text.setPlainText("")
        self._set_actions_enabled(False)

    @staticmethod
    def _compact_thread_text(value: str) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        return re.sub(r"\n(?:[ \t]*\n){2,}", "\n\n", text).strip()

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
        self._products_model.set_products(list(products))
        if not products:
            self._add_product_row(SendungProductLine())

    def _add_product_row(self, product: SendungProductLine) -> None:
        self._products_model.add_product(product)

    def _remove_selected_product_row(self) -> None:
        row = self._products.currentIndex().row()
        self._products_model.remove_row(row)

    def _address_lines(self) -> list[str]:
        return [line.strip() for line in self._address.toPlainText().splitlines() if line.strip()]

    def _products_from_table(self) -> list[SendungProductLine]:
        return self._products_model.products()

    @staticmethod
    def _manual_bool(value: object, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().casefold() not in {"", "0", "false", "no", "nein", "off"}

    def _validated_products(self) -> list[SendungProductLine] | None:
        products = self._products_from_table()
        for row, product in enumerate(products, start=1):
            if product.free_delivery:
                continue
            raw = str(product.delivery_price or "").strip().replace("€", "").replace(" ", "")
            try:
                amount = float(raw.replace(".", "").replace(",", "."))
            except ValueError:
                amount = 0.0
            if amount <= 0:
                QMessageBox.information(
                    self,
                    "Lieferpreis fehlt",
                    f"Bitte in Produktzeile {row} einen Lieferpreis eingeben (Standard: € 5,90).",
                )
                self._products.setCurrentIndex(self._products_model.index(row - 1, 5))
                self._products.edit(self._products_model.index(row - 1, 5))
                return None
        return products

    def _cell_text(self, row: int, column: int) -> str:
        index = self._products_model.index(row, column)
        value = index.data(Qt.ItemDataRole.DisplayRole) if index.isValid() else ""
        return str(value or "").strip()

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

        def job() -> int:
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
            summary=self._summary.text(),
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
        products = self._validated_products()
        if products is None:
            return None
        return (
            case.id,
            self._address_lines(),
            products,
            self._manual_text.toPlainText(),
            self._summary.text(),
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
            return self._service.open_count()

        self._start_action(
            self._btn_done,
            "Erledige...",
            job,
            self._on_mark_done_finished,
        )

    def _on_mark_done_finished(self, payload: object) -> None:
        try:
            remaining = int(payload)
        except (TypeError, ValueError):
            remaining = self._service.open_count()
        if remaining <= 0:
            QTimer.singleShot(0, self.accept)
            return
        self._load_cases(refresh=False)

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
