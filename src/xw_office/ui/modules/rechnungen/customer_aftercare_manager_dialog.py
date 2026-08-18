"""Lieferkorrekturen-Manager dialog: Zu prüfen / Fällig / Wartet / Erledigt / Alle (spec §7)."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.services.customer_aftercare import fulfillment as aftercare_fulfillment
from xw_office.services.customer_aftercare.service import MANAGER_FILTERS, CustomerAftercareService
from xw_office.services.sendungen.service import OffeneSendungenService
from xw_office.ui.modules.rechnungen.customer_aftercare_invoice_dialog import (
    CustomerAftercareInvoiceDialog,
)
from xw_office.ui.modules.rechnungen.offene_sendungen_dialog import OffeneSendungenDialog
from xw_office.ui.modules.rechnungen.customer_aftercare_review_dialog import (
    CASE_TYPE_LABELS,
    CustomerAftercareReviewDialog,
    ReviewDialogOutcome,
)

if TYPE_CHECKING:
    from xw_office.core.container import Container

_FILTER_LABELS: dict[str, str] = {
    "zu_pruefen": "Zu prüfen",
    "faellig": "Fällig",
    "wartet": "Wartet",
    "erledigt": "Erledigt",
    "alle": "Alle",
}


class CustomerAftercareManagerDialog(QDialog):
    """"Lieferkorrekturen" manager — master list + read-only detail pane (spec §7)."""

    def __init__(
        self,
        container: "Container",
        parent: QWidget | None = None,
        *,
        initial_filter: str = "alle",
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._service: CustomerAftercareService = container.resolve(CustomerAftercareService)
        self._cases: list[CustomerAftercareCase] = []
        self._selected_case: CustomerAftercareCase | None = None
        self._selected_items: list[CustomerAftercareItem] = []
        self._load_worker: BackgroundWorker | None = None
        self._detail_worker: BackgroundWorker | None = None
        self._action_worker: BackgroundWorker | None = None
        self._load_seq = 0
        self._detail_seq = 0
        self._build_ui()
        index = self._filter_combo.findData(initial_filter)
        if index >= 0:
            self._filter_combo.setCurrentIndex(index)
        QTimer.singleShot(0, self._load_cases)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._wait_for_workers()
        super().closeEvent(event)

    def accept(self) -> None:
        self._bump_seq()
        self._wait_for_workers()
        super().accept()

    def reject(self) -> None:
        self._bump_seq()
        self._wait_for_workers()
        super().reject()

    def _bump_seq(self) -> None:
        self._load_seq += 1
        self._detail_seq += 1

    def _wait_for_workers(self) -> None:
        for worker in (self._load_worker, self._detail_worker, self._action_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)

    def open_count(self) -> int:
        return self._service.count_pending_review() + self._service.count_due()

    def _build_ui(self) -> None:
        self.setWindowTitle("Lieferkorrekturen")
        self.setMinimumSize(900, 600)
        self.resize(1200, 760)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Filter:"))
        self._filter_combo = QComboBox()
        for key in MANAGER_FILTERS:
            self._filter_combo.addItem(_FILTER_LABELS[key], key)
        self._filter_combo.currentIndexChanged.connect(lambda _index: self._load_cases())
        top.addWidget(self._filter_combo)
        self._status = QLabel("-")
        top.addWidget(self._status, stretch=1)
        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(self._load_cases)
        top.addWidget(self._btn_refresh)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
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
        right_content = QWidget()
        right_lay = QVBoxLayout(right_content)
        right_lay.setContentsMargins(10, 0, 10, 0)
        right.setWidget(right_content)
        right_outer_lay.addWidget(right, stretch=1)

        self._meta = QLabel("Kein Fall ausgewählt")
        self._meta.setWordWrap(True)
        right_lay.addWidget(self._meta)

        right_lay.addWidget(QLabel("Artikel:"))
        self._items_view = QPlainTextEdit()
        self._items_view.setReadOnly(True)
        self._items_view.setMinimumHeight(100)
        self._items_view.setMaximumHeight(160)
        right_lay.addWidget(self._items_view)

        right_lay.addWidget(QLabel("Notiz:"))
        self._note_view = QPlainTextEdit()
        self._note_view.setReadOnly(True)
        self._note_view.setMinimumHeight(60)
        self._note_view.setMaximumHeight(90)
        right_lay.addWidget(self._note_view)

        row_actions = QHBoxLayout()
        self._btn_review = QPushButton("Prüfen / Bestätigen…")
        self._btn_review.clicked.connect(self._open_review_dialog)
        row_actions.addWidget(self._btn_review)
        self._btn_invoice = QPushButton("Zusatzrechnung…")
        self._btn_invoice.clicked.connect(self._open_invoice_dialog)
        row_actions.addWidget(self._btn_invoice)
        self._btn_nachsendung = QPushButton("Nachsendung vorbereiten…")
        self._btn_nachsendung.clicked.connect(self._prepare_nachsendung)
        row_actions.addWidget(self._btn_nachsendung)
        self._btn_resolve = QPushButton("Als erledigt markieren")
        self._btn_resolve.clicked.connect(self._mark_resolved)
        row_actions.addWidget(self._btn_resolve)
        self._btn_cancel = QPushButton("Stornieren")
        self._btn_cancel.clicked.connect(self._mark_cancelled)
        row_actions.addWidget(self._btn_cancel)
        row_actions.addStretch(1)
        right_outer_lay.addLayout(row_actions)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def _current_filter(self) -> str:
        return str(self._filter_combo.currentData() or "alle")

    def _load_cases(self) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self._bump_seq()
        seq = self._load_seq
        filter_key = self._current_filter()
        self._status.setText("Lade Lieferkorrekturen…")

        def job() -> list[CustomerAftercareCase]:
            return self._service.list_cases_for_filter(filter_key)

        def on_result(cases: object) -> None:
            if seq != self._load_seq:
                return
            self._cases = cases if isinstance(cases, list) else []
            self._populate_list()
            self._status.setText(f"{len(self._cases)} Fälle")

        def on_error(exc: Exception) -> None:
            if seq != self._load_seq:
                return
            self._status.setText(f"Fehler beim Laden: {exc}")

        worker = BackgroundWorker(job)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(lambda: setattr(self, "_load_worker", None))
        self._load_worker = worker
        worker.start()

    def _populate_list(self) -> None:
        self._list.clear()
        for case in self._cases:
            label = (
                f"{case.customer_name or case.customer_email or '—'} — "
                f"{CASE_TYPE_LABELS.get(case.case_type or case.ai_suggested_type, case.case_type or '—')} "
                f"[{case.status}]"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(case.id))
            self._list.addItem(item)
        self._meta.setText("Kein Fall ausgewählt")
        self._items_view.setPlainText("")
        self._note_view.setPlainText("")
        self._selected_case = None
        self._selected_items = []

    def _on_case_selected(self, row: int) -> None:
        if not (0 <= row < len(self._cases)):
            self._selected_case = None
            self._selected_items = []
            return
        case = self._cases[row]
        self._selected_case = case
        self._meta.setText(
            f"Kunde: {case.customer_name or case.customer_email or '—'}\n"
            f"Wix-Bestellung: {case.source_wix_order_number or '—'}\n"
            f"Falltyp: {CASE_TYPE_LABELS.get(case.case_type or case.ai_suggested_type, case.case_type or '—')}\n"
            f"Status: {case.status}\n"
            f"Kulanz: {'Ja' if case.courtesy else 'Nein'}\n"
            f"Trigger: {case.trigger_reason or '—'}\n"
            f"Fälligkeit: {case.due_at or '—'}"
        )
        self._note_view.setPlainText(case.note or "")
        self._load_items(case.id)

    def _load_items(self, case_id: uuid.UUID) -> None:
        self._detail_seq += 1
        seq = self._detail_seq

        def job() -> list[CustomerAftercareItem]:
            return self._service.get_items(case_id)

        def on_result(items: object) -> None:
            if seq != self._detail_seq:
                return
            rows = items if isinstance(items, list) else []
            self._selected_items = rows
            lines = [f"{item.role}: {item.quantity}x {item.name} ({item.sku})" for item in rows]
            self._items_view.setPlainText("\n".join(lines) or "—")

        worker = BackgroundWorker(job)
        worker.signals.result.connect(on_result)
        worker.signals.finished.connect(lambda: setattr(self, "_detail_worker", None))
        self._detail_worker = worker
        worker.start()

    def _open_review_dialog(self) -> None:
        case = self._selected_case
        if case is None:
            return
        dialog = CustomerAftercareReviewDialog(
            case, self._selected_items, config=self._container.config, parent=self
        )
        dialog.exec()
        outcome = dialog.outcome()
        if outcome is None:
            return
        self._apply_outcome(case.id, outcome)

    def _open_invoice_dialog(self) -> None:
        case = self._selected_case
        if case is None:
            return
        dialog = CustomerAftercareInvoiceDialog(self._container, case, self._selected_items, parent=self)
        dialog.exec()
        if dialog.action_taken in {"invoiced", "skipped"}:
            self._load_cases()

    def _prepare_nachsendung(self) -> None:
        case = self._selected_case
        if case is None:
            return
        missing_lines = aftercare_fulfillment.missing_items_as_product_lines(self._selected_items)
        if not missing_lines:
            self._status.setText("Kein fehlender Artikel fuer diesen Fall hinterlegt.")
            return
        if self._action_worker is not None and self._action_worker.isRunning():
            return

        sendungen: OffeneSendungenService = self._container.resolve(OffeneSendungenService)
        note = aftercare_fulfillment.replacement_shipment_note(case)
        manual_case_id = aftercare_fulfillment.manual_case_id(case)

        def job() -> None:
            sendungen.create_manual_case(
                case_id=manual_case_id,
                subject=f"Lieferkorrektur {case.source_wix_order_number or case.customer_name}".strip(),
                note=note,
                products=missing_lines,
            )

        def on_result(_result: object) -> None:
            dlg = OffeneSendungenDialog(self._container, self)
            dlg.exec()

        def on_error(exc: Exception) -> None:
            self._status.setText(f"Nachsendung konnte nicht vorbereitet werden: {exc}")

        worker = BackgroundWorker(job)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(lambda: setattr(self, "_action_worker", None))
        self._action_worker = worker
        worker.start()

    def _apply_outcome(self, case_id: uuid.UUID, outcome: ReviewDialogOutcome) -> None:
        if outcome.action == "defer":
            return  # stays PENDING_REVIEW — no service call needed
        if outcome.action == "confirm":
            self._run_action(
                lambda: self._service.confirm_case(
                    case_id, case_type=outcome.case_type, courtesy=outcome.courtesy, note=outcome.note
                )
            )
        elif outcome.action == "ignore":
            self._run_action(lambda: self._service.ignore_case(case_id))

    def _mark_resolved(self) -> None:
        case = self._selected_case
        if case is None:
            return
        self._run_action(lambda: self._service.mark_resolved(case.id))

    def _mark_cancelled(self) -> None:
        case = self._selected_case
        if case is None:
            return
        self._run_action(lambda: self._service.mark_cancelled(case.id))

    def _run_action(self, fn: Any) -> None:
        if self._action_worker is not None and self._action_worker.isRunning():
            return

        def on_result(_result: object) -> None:
            self._load_cases()

        def on_error(exc: Exception) -> None:
            self._status.setText(f"Aktion fehlgeschlagen: {exc}")

        worker = BackgroundWorker(fn)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(lambda: setattr(self, "_action_worker", None))
        self._action_worker = worker
        worker.start()
