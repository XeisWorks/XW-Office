"""Tagesgeschäft — Rechnungen hub with start/reprint actions."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent, QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QToolButton,
    QMenu,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.types import ModuleKey
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.background_jobs.service import BackgroundJobManager
from xw_studio.services.daily_business.service import DailyBusinessService
from xw_studio.services.draft_invoice.service import (
    DraftInvoiceService,
    ProductIssueDecision,
    ProductIssueTarget,
    ProductPreflightApplyResult,
    ProductPreflightPlan,
)
from xw_studio.services.inventory.service import (
    InventoryService,
    ReprintExecutionReport,
    ReprintPreflight,
    StartExecutionReport,
    StartMode,
    StartPreflight,
)
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.sendungen.service import OffeneSendungenService
from xw_studio.services.transfers.service import OffeneUeberweisungenService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.ui.modules.rechnungen.product_preflight_dialog import ProductPreflightDialog
from xw_studio.ui.modules.rechnungen.reprint_dialog import ReprintPreviewDialog
from xw_studio.ui.modules.rechnungen.view import RechnungenView
from xw_studio.ui.widgets.data_table import DataTable
from xw_studio.ui.widgets.search_bar import SearchBar

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_QUEUE_COLUMNS = ["Ref", "Kunde", "Betrag", "Status", "Hinweis", "Mark."]
_BADGE_JOB_QUEUE = "badge-refresh"


class _QueueTabView(QWidget):
    """Generic queue tab for Mollie/Gutscheine/Downloads/Refunds."""

    def __init__(self, container: Container, queue_name: str, title: str) -> None:
        super().__init__()
        self._container = container
        self._queue_name = queue_name
        self._title = title
        self._worker: BackgroundWorker | None = None
        self._rows: list[dict[str, str]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._caption = QLabel(self._title)
        self._caption.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self._caption)

        row = QHBoxLayout()
        self._search = SearchBar("Suchen…")
        self._search.search_changed.connect(self._on_search)
        self._search.set_suggestion_provider(self._queue_search_suggestions)
        row.addWidget(self._search, stretch=1)
        self._count_lbl = QLabel("0 Eintraege")
        row.addWidget(self._count_lbl)
        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(lambda: self.reload())
        row.addWidget(self._btn_refresh)
        layout.addLayout(row)

        self._table = DataTable(_QUEUE_COLUMNS)
        layout.addWidget(self._table, stretch=1)
        self._detail = QLabel("Zeile waehlen fuer Details …")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #9e9e9e; padding: 6px 2px;")
        layout.addWidget(self._detail)

        sel = self._table.selectionModel()
        if sel is not None:
            sel.selectionChanged.connect(self._on_selection_changed)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)

    def reload(self, fallback_count: int = 0) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._btn_refresh.setEnabled(False)

        def job() -> list[dict[str, str]]:
            service: DailyBusinessService = self._container.resolve(DailyBusinessService)
            return service.load_queue_rows(self._queue_name, fallback_count=fallback_count)

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_load_result)
        self._worker.signals.error.connect(self._on_load_error)
        self._worker.signals.finished.connect(lambda: self._btn_refresh.setEnabled(True))
        self._worker.start()

    def _on_load_result(self, result: object) -> None:
        rows = result if isinstance(result, list) else []
        norm_rows = [r for r in rows if isinstance(r, dict)]
        self._rows = norm_rows
        self._table.set_data(norm_rows)
        self._search.refresh_suggestions()
        self._count_lbl.setText(f"{len(norm_rows)} Eintraege")
        self._detail.setText("Zeile waehlen fuer Details …")

    def _on_load_error(self, exc: Exception) -> None:
        logger.warning("Queue '%s' load failed: %s", self._queue_name, exc)
        self._count_lbl.setText("Fehler")

    def _on_search(self, text: str) -> None:
        self._table.set_filter(text, column=0)

    def _queue_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 3:
            return []
        items: list[str] = []
        for row in self._rows:
            hay = f"{row.get('Ref', '')} {row.get('Kunde', '')} {row.get('Status', '')} {row.get('Hinweis', '')}".lower()
            if q in hay:
                items.append(f"{row.get('Ref', '—')} - {row.get('Kunde', '—')}")
        return items

    def _on_selection_changed(self, _selected: object, _deselected: object) -> None:
        row = self._table.selected_row_data() or {}
        if not row:
            self._detail.setText("Zeile waehlen fuer Details …")
            return
        self._detail.setText(
            f"Ref: {row.get('Ref', '—')}\n"
            f"Kunde: {row.get('Kunde', '—')}\n"
            f"Betrag: {row.get('Betrag', '—')}\n"
            f"Status: {row.get('Status', '—')}\n"
            f"Hinweis: {row.get('Hinweis', '—')}"
        )


class QueuePopupDialog(QDialog):
    """Popup wrapper for the Daily-Business queue views."""

    def __init__(
        self,
        container: Container,
        *,
        queue_name: str,
        title: str,
        fallback_count: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(940, 560)
        layout = QVBoxLayout(self)
        self._view = _QueueTabView(container, queue_name, title)
        layout.addWidget(self._view, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._view.reload(fallback_count=fallback_count)


class _StartDialog(QDialog):
    """Pre-flight dialog for the ▶ START workflow."""

    def __init__(
        self,
        preflight: StartPreflight,
        initial_mode: StartMode = StartMode.INVOICES_AND_PRINT,
        *,
        allow_mode_selection: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._preflight = preflight
        self.setWindowTitle("Tagesgeschäft starten")
        self.setMinimumWidth(640)
        self.setMinimumHeight(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel(
            "Wähle den gewünschten Modus für den Tagesstart.\n"
            "Die Rückmeldungen aus dem Lager und aus Mollie werden danach automatisch geladen."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        gb = QGroupBox("Modus")
        gb_lay = QVBoxLayout(gb)
        self._mode_invoices = QPushButton("📄  Nur Rechnungen")
        self._mode_invoices.setCheckable(True)
        self._mode_invoices.setMinimumHeight(40)
        self._mode_full = QPushButton("📄 + 🖨  Rechnungen + Druck (Noten & Labels vorbereiten)")
        self._mode_full.setCheckable(True)
        self._mode_full.setMinimumHeight(40)
        # Full mode (invoice + label printing) remains available even when
        # inventory preflight data is missing; only stock updates are skipped.
        self._mode_full.setEnabled(True)
        self._mode_invoices.setChecked(initial_mode != StartMode.INVOICES_AND_PRINT)
        self._mode_full.setChecked(initial_mode == StartMode.INVOICES_AND_PRINT)
        if not allow_mode_selection:
            self._mode_invoices.setEnabled(False)
            self._mode_full.setEnabled(False)
        gb_lay.addWidget(self._mode_invoices)
        gb_lay.addWidget(self._mode_full)
        layout.addWidget(gb)

        gb_preview = QGroupBox("Pre-Flight (Bestand vs. Bedarf)")
        preview_layout = QVBoxLayout(gb_preview)
        self._preview_text = QPlainTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setMinimumHeight(260)
        self._preview_text.setPlainText(self._format_preflight())
        preview_layout.addWidget(self._preview_text)
        layout.addWidget(gb_preview)

        # Mutual exclusion
        self._mode_invoices.toggled.connect(lambda c: self._mode_full.setChecked(not c) if c else None)
        self._mode_full.toggled.connect(lambda c: self._mode_invoices.setChecked(not c) if c else None)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def full_mode(self) -> bool:
        return bool(self._mode_full.isChecked())

    @property
    def selected_mode(self) -> StartMode:
        return StartMode.INVOICES_AND_PRINT if self.full_mode else StartMode.INVOICES_ONLY

    def _format_preflight(self) -> str:
        lines: list[str] = [
            f"Entwürfe zur Abarbeitung: {self._preflight.open_invoice_count}",
            "",
        ]
        if self._preflight.missing_position_data:
            lines.extend(
                [
                    "Noch keine Artikel-Positionsdaten für den Druckplan vorhanden.",
                    "Lege für die nächste Ausbaustufe die Queue als JSON in der DB an:",
                    "Key: daily_business.pending_requirements",
                    "Beispiel: {\"XW-4-001\": 7, \"XW-6-003\": 2}",
                ]
            )
            return "\n".join(lines)

        if not self._preflight.decisions:
            lines.append("Keine Druckjobs für den aktuellen Queue-Stand.")
            return "\n".join(lines)

        lines.append("SKU | Bedarf | Lager | Fehlmenge | Druck inkl. Puffer | Aktion")
        lines.append("-" * 72)
        for decision in self._preflight.decisions:
            action = "DRUCK" if decision.will_print else "OK"
            lines.append(
                f"{decision.sku} | {decision.required_qty} | {decision.on_hand_qty} | "
                f"{decision.missing_qty} | {decision.final_print_qty} | {action}"
            )
        return "\n".join(lines)


class TagesgeschaeftView(QWidget):
    """Daily-Business hub for Rechnungen with top action bar."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._background_jobs = container.resolve(BackgroundJobManager)
        self._rechnungen_view: RechnungenView | None = None
        self._badge_worker: BackgroundWorker | None = None
        self._start_worker: BackgroundWorker | None = None
        self._start_product_worker: BackgroundWorker | None = None
        self._start_exec_worker: BackgroundWorker | None = None
        self._reprint_worker: BackgroundWorker | None = None
        self._reprint_exec_worker: BackgroundWorker | None = None
        self._start_requested_mode: StartMode = StartMode.INVOICES_AND_PRINT
        self._start_selected_mode: StartMode = StartMode.INVOICES_AND_PRINT
        self._start_include_product_print = False
        self._start_selected_invoice_ids: list[str] = []
        self._start_selected_summaries: list[InvoiceSummary] = []
        self._start_selected_only = False
        self._sendungen_count = 0
        self._transfer_count = 0
        self._mollie_count = 0
        self._sendungen_live_refresh_ts = 0.0
        self._pending_start_preflight: StartPreflight | None = None
        self._start_product_preflight_started_at = 0.0
        self._start_abort_requested = False
        self._badge_timer = QTimer(self)
        self._badge_timer.setInterval(60000)
        self._badge_timer.timeout.connect(self._refresh_badges)
        self._build_ui()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._refresh_badges()
        self._badge_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._badge_timer.stop()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._badge_timer.stop()
        self._wait_for_workers()
        super().closeEvent(event)

    def has_active_flow(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in (
                self._start_worker,
                self._start_product_worker,
                self._start_exec_worker,
                self._reprint_worker,
                self._reprint_exec_worker,
            )
        )

    def prepare_shutdown(self) -> None:
        self._badge_timer.stop()
        self._wait_for_workers()

    def _wait_for_workers(self) -> None:
        for worker in (self._badge_worker, self._start_worker, self._start_product_worker, self._start_exec_worker,
                       self._reprint_worker, self._reprint_exec_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)

    def _build_ui(self) -> None:
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        action_bar = QWidget()
        action_bar.setFixedHeight(44)
        bar_lay = QHBoxLayout(action_bar)
        bar_lay.setContentsMargins(12, 4, 12, 4)
        bar_lay.setSpacing(8)

        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.setToolTip("Erste Rechnungsseite neu laden")
        self._btn_refresh.setFixedHeight(34)
        self._btn_refresh.clicked.connect(self._reload_invoice_view)
        bar_lay.addWidget(self._btn_refresh)

        self._btn_draft = QPushButton("Entwurf")
        self._btn_draft.setToolTip("Neuen sevDesk-Rechnungsentwurf aus Wix-Order-Nr erstellen")
        self._btn_draft.setFixedHeight(34)
        self._btn_draft.clicked.connect(self._create_invoice_draft)
        bar_lay.addWidget(self._btn_draft)

        self._btn_custom_label = QPushButton("Custom-Label")
        self._btn_custom_label.setToolTip("Freie Lieferadresse eingeben und direkt als Label drucken")
        self._btn_custom_label.setFixedHeight(34)
        self._btn_custom_label.clicked.connect(self._open_custom_label)
        bar_lay.addWidget(self._btn_custom_label)

        bar_lay.addStretch()

        self._btn_start = QToolButton()
        self._btn_start.setText("▶ START")
        self._btn_start.setToolTip("START: Rechnungen + Labels + Fulfillment + Mail")
        self._btn_start.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._btn_start.setFixedHeight(34)
        self._btn_start.setFixedWidth(145)
        self._btn_start.setStyleSheet(
            "QToolButton { background-color: #1976d2; color: white; border-radius: 6px;"
            " font-weight: bold; font-size: 13px; }"
            " QToolButton:hover { background-color: #1565c0; }"
            " QToolButton:pressed { background-color: #0d47a1; }"
            " QToolButton::menu-button { border-left: 1px solid rgba(255,255,255,0.35); width: 26px; }"
            " QToolButton::menu-arrow { image: none; }"
        )
        self._btn_start.clicked.connect(
            lambda: self._on_start_clicked(StartMode.INVOICES_AND_PRINT, include_product_print=False)
        )
        self._start_button_idle_text = self._btn_start.text()
        start_menu = QMenu(self._btn_start)
        start_menu.addAction("Selected").triggered.connect(
            lambda: self._on_start_clicked(StartMode.INVOICES_AND_PRINT, selected_only=True, include_product_print=False)
        )
        start_menu.addAction("+ Noten").triggered.connect(
            lambda: self._on_start_clicked(StartMode.INVOICES_AND_PRINT, selected_only=False, include_product_print=True)
        )
        start_menu.addAction("+ Noten Selected").triggered.connect(
            lambda: self._on_start_clicked(StartMode.INVOICES_AND_PRINT, selected_only=True, include_product_print=True)
        )
        self._btn_start.setMenu(start_menu)

        self._btn_stop = QPushButton("STOP")
        self._btn_stop.setToolTip("Laufenden START nach der aktuellen Rechnung anhalten")
        self._btn_stop.setFixedHeight(34)
        self._btn_stop.setFixedWidth(100)
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet(
            "QPushButton { background-color: #ef6c00; color: white; border-radius: 6px;"
            " font-weight: bold; font-size: 13px; }"
            " QPushButton:hover { background-color: #e65100; }"
            " QPushButton:pressed { background-color: #bf360c; }"
            " QPushButton:disabled { background-color: #cfd8dc; color: #607d8b; }"
        )
        self._btn_stop.clicked.connect(self._on_start_stop_clicked)

        self._btn_sendungen_alert = self._build_alert_button("OFFENE SENDUNGEN")
        self._btn_sendungen_alert.clicked.connect(self._on_sendungen_alert_clicked)
        self._btn_sendungen_alert.hide()
        bar_lay.addWidget(self._btn_sendungen_alert)

        self._btn_transfer_alert = self._build_alert_button("UEBERWEISUNG OFFEN")
        self._btn_transfer_alert.clicked.connect(self._on_transfer_alert_clicked)
        self._btn_transfer_alert.hide()
        bar_lay.addWidget(self._btn_transfer_alert)

        self._btn_mollie_alert = self._build_alert_button("MOLLIE AUTH")
        self._btn_mollie_alert.clicked.connect(self._on_mollie_alert_clicked)
        self._btn_mollie_alert.hide()
        bar_lay.addWidget(self._btn_mollie_alert)

        bar_lay.addSpacing(18)
        bar_lay.addWidget(self._btn_start)
        bar_lay.addWidget(self._btn_stop)

        self._btn_beenden = QPushButton("■  Beenden")
        self._btn_beenden.setToolTip("App beenden (laufende Hintergrundaufgaben werden abgewartet)")
        self._btn_beenden.setFixedHeight(34)
        self._btn_beenden.setFixedWidth(130)
        self._btn_beenden.setStyleSheet(
            "QPushButton { background-color: #c62828; color: white; border-radius: 6px;"
            " font-weight: bold; font-size: 13px; }"
            " QPushButton:hover { background-color: #b71c1c; }"
            " QPushButton:pressed { background-color: #7f0000; }"
        )
        self._btn_beenden.clicked.connect(self._on_beenden_clicked)
        bar_lay.addWidget(self._btn_beenden)

        self._main_layout.addWidget(action_bar)

        self._invoice_loading = QLabel("Rechnungen-Oberflaeche wird vorbereitet...")
        self._invoice_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._invoice_loading.setStyleSheet("font-size: 16px; color: #64748b;")
        self._main_layout.addWidget(self._invoice_loading, stretch=1)
        self._set_invoice_ui_ready(False)
        QTimer.singleShot(0, self._materialize_rechnungen_view)

    def _materialize_rechnungen_view(self) -> None:
        if self._rechnungen_view is not None:
            return
        view = RechnungenView(self._container)
        view.set_badge_refresh_managed_externally(True)
        view.set_top_actions_managed_externally(True)
        self._rechnungen_view = view
        self._main_layout.replaceWidget(self._invoice_loading, view)
        self._invoice_loading.deleteLater()
        self._set_invoice_ui_ready(True)

    def _set_invoice_ui_ready(self, ready: bool) -> None:
        for button in (self._btn_refresh, self._btn_draft, self._btn_custom_label, self._btn_start):
            button.setEnabled(ready)

    def _reload_invoice_view(self) -> None:
        if self._rechnungen_view is not None:
            self._rechnungen_view.reload_first_page()

    def _create_invoice_draft(self) -> None:
        if self._rechnungen_view is not None:
            self._rechnungen_view.create_draft_from_wix_order()

    def _open_custom_label(self) -> None:
        if self._rechnungen_view is not None:
            self._rechnungen_view.open_custom_label_dialog()

    def _build_alert_button(self, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setFixedHeight(34)
        button.setStyleSheet(
            "QPushButton {"
            "background-color: #b91c1c; color: white; border-radius: 6px;"
            "font-weight: bold; padding: 0 14px;"
            "}"
            "QPushButton:hover { background-color: #991b1b; }"
            "QPushButton:pressed { background-color: #7f1d1d; }"
        )
        return button

    def _refresh_badges(self) -> None:
        self._background_jobs.submit(
            queue=_BADGE_JOB_QUEUE,
            priority=10,
            coalesce_key="tagesgeschaeft-badges",
            start_fn=self._create_badge_refresh_worker,
            can_start=lambda: self._badge_worker is None or not self._badge_worker.isRunning(),
        )

    def _create_badge_refresh_worker(self) -> BackgroundWorker | None:
        if self._badge_worker is not None and self._badge_worker.isRunning():
            return None

        def job() -> dict[str, int]:
            invoice_service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            open_count = invoice_service.count_invoices(status=100)
            service: DailyBusinessService = self._container.resolve(DailyBusinessService)
            counts = service.load_counts(open_invoice_count=open_count)
            sendungen_service: OffeneSendungenService = self._container.resolve(OffeneSendungenService)
            now = time.monotonic()
            if now - self._sendungen_live_refresh_ts >= 300.0:
                counts["sendungen"] = max(
                    0,
                    int(sendungen_service.refresh_count_from_graph_silent(lookback_days=20, max_items=150)),
                )
                self._sendungen_live_refresh_ts = now
            else:
                counts["sendungen"] = max(0, int(sendungen_service.open_count()))
            transfer_service: OffeneUeberweisungenService = self._container.resolve(OffeneUeberweisungenService)
            try:
                counts["transfer"] = max(
                    0,
                    int(transfer_service.refresh_count_from_graph_silent(lookback_days=60, max_items=150)),
                )
                counts["transfer_login_required"] = (
                    1
                    if counts["transfer"] == 0 and transfer_service.needs_interactive_graph_login()
                    else 0
                )
            except Exception:  # noqa: BLE001
                counts["transfer"] = max(0, int(counts.get("transfers", 0)))
                counts["transfer_login_required"] = 0
            return counts

        self._badge_worker = BackgroundWorker(job)
        self._badge_worker.signals.result.connect(self._on_badges_result)
        self._badge_worker.signals.error.connect(self._on_badges_error)
        self._badge_worker.signals.finished.connect(lambda: setattr(self, "_badge_worker", None))
        return self._badge_worker

    def _on_badges_result(self, result: object) -> None:
        counts = result if isinstance(result, dict) else {}
        open_count = max(0, int(counts.get("rechnungen", 0)))
        mollie_count = max(0, int(counts.get("mollie", 0)))
        gutscheine_count = max(0, int(counts.get("gutscheine", 0)))
        sendungen_count = max(0, int(counts.get("sendungen", 0)))
        transfer_count = max(0, int(counts.get("transfer", counts.get("refunds", 0))))
        transfer_login_required = bool(counts.get("transfer_login_required"))

        self._sendungen_count = sendungen_count
        self._transfer_count = transfer_count
        self._mollie_count = mollie_count
        self._update_alert_button(self._btn_sendungen_alert, "OFFENE SENDUNGEN", sendungen_count)
        if transfer_count > 0:
            self._update_alert_button(self._btn_transfer_alert, "UEBERWEISUNG OFFEN", transfer_count)
        elif transfer_login_required:
            self._btn_transfer_alert.setText("UEBERWEISUNG LOGIN")
            self._btn_transfer_alert.show()
        else:
            self._update_alert_button(self._btn_transfer_alert, "UEBERWEISUNG OFFEN", 0)
        self._update_alert_button(self._btn_mollie_alert, "MOLLIE AUTH", mollie_count)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.badge_updated.emit(ModuleKey.RECHNUNGEN.value, open_count)
        signals.badge_updated.emit(ModuleKey.GUTSCHEINE.value, gutscheine_count)
        signals.badge_updated.emit(ModuleKey.MOLLIE.value, mollie_count)

    def _on_badges_error(self, exc: Exception) -> None:
        logger.warning("Badge refresh failed: %s", exc)

    @staticmethod
    def _update_alert_button(button: QPushButton, label: str, count: int) -> None:
        if count > 0:
            button.setText(f"{label} ({count})")
            button.show()
            return
        button.hide()

    def _on_sendungen_alert_clicked(self) -> None:
        if self._rechnungen_view is None:
            return
        count = self._rechnungen_view.open_sendungen_dialog()
        self._sendungen_count = max(0, int(count))
        self._update_alert_button(self._btn_sendungen_alert, "OFFENE SENDUNGEN", self._sendungen_count)

    def _on_transfer_alert_clicked(self) -> None:
        if self._rechnungen_view is None:
            return
        count = self._rechnungen_view.open_ueberweisungen_dialog()
        self._transfer_count = max(0, int(count))
        self._update_alert_button(self._btn_transfer_alert, "UEBERWEISUNG OFFEN", self._transfer_count)

    def _on_mollie_alert_clicked(self) -> None:
        if self._rechnungen_view is None:
            return
        self._rechnungen_view.open_queue_dialog(
            "mollie",
            "MOLLIE AUTHORIZATION",
            fallback_count=self._mollie_count,
        )
        self._refresh_badges()

    def _on_start_clicked(
        self,
        requested_mode: StartMode = StartMode.INVOICES_AND_PRINT,
        *,
        selected_only: bool = False,
        include_product_print: bool = False,
    ) -> None:
        if self.has_active_flow() or (self._start_worker is not None and self._start_worker.isRunning()):
            return
        self._start_requested_mode = requested_mode
        self._start_include_product_print = bool(include_product_print)
        self._start_selected_only = bool(selected_only)
        self._start_selected_invoice_ids = []
        self._start_selected_summaries = []
        if selected_only:
            if self._rechnungen_view is None:
                return
            selected = self._rechnungen_view.selected_summaries()
            self._start_selected_summaries = list(selected)
            self._start_selected_invoice_ids = [
                str(summary.id).strip() for summary in selected if str(summary.id).strip()
            ]
            if not self._start_selected_invoice_ids:
                QMessageBox.information(
                    self,
                    "START SELECTED",
                    "Bitte zuerst eine oder mehrere Rechnungen markieren.",
                )
                return

        signals: AppSignals = self._container.resolve(AppSignals)
        self._start_abort_requested = False
        self._set_start_running(True, allow_stop=True)
        scope = (
            f"{len(self._start_selected_invoice_ids)} markierte Rechnung(en)"
            if self._start_selected_only
            else "alle offenen Entwuerfe"
        )
        if self._rechnungen_view is not None:
            self._rechnungen_view.show_start_summary(
                [
                    "START wird vorbereitet.",
                    f"Umfang: {scope}",
                    f"Notendruck: {'ja' if self._start_include_product_print else 'nein'}",
                ]
            )
        signals.status_message.emit("Pre-Flight wird erstellt…", 2500)

        def job() -> StartPreflight:
            invoice_service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            open_count = (
                len(self._start_selected_invoice_ids)
                if self._start_selected_only
                else invoice_service.count_invoices(status=100)
            )
            if not self._start_include_product_print:
                return StartPreflight(
                    open_invoice_count=open_count,
                    decisions=[],
                    missing_position_data=True,
                )
            inventory_service: InventoryService = self._container.resolve(InventoryService)
            requirements = invoice_service.build_inventory_requirements(
                invoice_ids=(
                    list(self._start_selected_invoice_ids)
                    if self._start_selected_only
                    else None
                )
            )
            return inventory_service.build_start_preflight(
                open_count,
                requirements=requirements,
            )

        self._start_worker = BackgroundWorker(job)
        self._start_worker.signals.result.connect(self._on_start_preflight_ready)
        self._start_worker.signals.error.connect(self._on_start_preflight_error)
        self._start_worker.start()

    def _on_start_preflight_ready(self, result: object) -> None:
        if self._start_abort_requested:
            self._pending_start_preflight = None
            self._set_start_running(False)
            signals: AppSignals = self._container.resolve(AppSignals)
            signals.status_message.emit("START gestoppt", 2500)
            return
        if not isinstance(result, StartPreflight):
            self._set_start_running(False)
            return
        signals: AppSignals = self._container.resolve(AppSignals)
        self._start_selected_mode = StartMode.INVOICES_AND_PRINT
        self._pending_start_preflight = result
        if not self._start_include_product_print:
            logger.info(
                "Tagesgeschaeft START: direct invoice flow selected_only=%s",
                self._start_selected_only,
            )
            self._start_missing_product_check()
            return
        dlg = _StartDialog(
            result,
            initial_mode=StartMode.INVOICES_AND_PRINT,
            allow_mode_selection=False,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._set_start_running(False)
            signals.status_message.emit("START abgebrochen", 2500)
            return
        logger.info(
            "Tagesgeschäft START: mode=%s include_product_print=%s selected_only=%s",
            self._start_selected_mode.value,
            self._start_include_product_print,
            self._start_selected_only,
        )

        if (
            (self._start_product_worker is not None and self._start_product_worker.isRunning())
            or (self._start_exec_worker is not None and self._start_exec_worker.isRunning())
        ):
            return

        signals.status_message.emit("Produktprüfung wird vorbereitet…", 2500)

        self._start_missing_product_check()

    def _start_missing_product_check(self) -> None:
        if (
            (self._start_product_worker is not None and self._start_product_worker.isRunning())
            or (self._start_exec_worker is not None and self._start_exec_worker.isRunning())
        ):
            self._btn_start.setEnabled(False)
            return

        self._start_product_preflight_started_at = time.perf_counter()

        def job() -> ProductPreflightPlan:
            invoice_service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            draft_service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
            if self._start_selected_only:
                summaries = list(self._start_selected_summaries)
            else:
                summaries = invoice_service.load_invoice_summaries(status=100, limit=1000, offset=0)
            targets_by_reference: dict[str, list[ProductIssueTarget]] = {}
            refs: list[str] = []
            for summary in summaries:
                reference = str(summary.order_reference or "").strip()
                if not reference:
                    continue
                refs.append(reference)
                targets_by_reference.setdefault(reference, []).append(
                    ProductIssueTarget(
                        invoice_id=str(summary.id or "").strip(),
                        invoice_number=str(summary.invoice_number or "").strip(),
                        wix_order_number=reference,
                        customer_name=str(summary.contact_name or "").strip(),
                    )
                )
            return draft_service.build_missing_product_plan(refs, targets_by_reference=targets_by_reference)

        self._start_product_worker = BackgroundWorker(job)
        self._start_product_worker.signals.result.connect(self._on_start_product_preflight_ready)
        self._start_product_worker.signals.error.connect(self._on_start_preflight_error)
        self._start_product_worker.signals.finished.connect(lambda: setattr(self, "_start_product_worker", None))
        self._start_product_worker.start()

    def _on_start_product_preflight_ready(self, result: object) -> None:
        if self._start_abort_requested:
            self._pending_start_preflight = None
            self._set_start_running(False)
            signals: AppSignals = self._container.resolve(AppSignals)
            signals.status_message.emit("START gestoppt", 2500)
            return
        plan = result if isinstance(result, ProductPreflightPlan) else ProductPreflightPlan(issues=[], part_categories=[])
        preflight_elapsed_ms = int(
            (time.perf_counter() - self._start_product_preflight_started_at) * 1000
        ) if self._start_product_preflight_started_at else 0
        self._start_product_preflight_started_at = 0.0
        dialog_started = time.perf_counter()
        decisions = self._run_product_preflight_dialogs(plan)
        logger.info(
            "START metric product_preflight_ms=%s product_dialog_ms=%s issues=%s selected_only=%s",
            preflight_elapsed_ms,
            int((time.perf_counter() - dialog_started) * 1000),
            len(plan.issues),
            self._start_selected_only,
        )
        preflight = self._pending_start_preflight
        mode = self._start_selected_mode
        if preflight is None:
            self._set_start_running(False)
            QMessageBox.warning(self, "START", "START-Preflight ist nicht mehr verfuegbar.")
            return
        if self._start_exec_worker is not None and self._start_exec_worker.isRunning():
            self._btn_start.setEnabled(False)
            return

        self._start_abort_requested = False
        self._set_start_running(True, allow_stop=True)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("START wird ausgefuehrt…", 2500)

        def job() -> dict[str, object]:
            draft_service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
            product_apply_started = time.perf_counter()
            apply_result = (
                draft_service.apply_missing_product_plan(plan, decisions)
                if plan.issues
                else ProductPreflightApplyResult()
            )
            logger.info(
                "START metric product_apply_ms=%s issues=%s created=%s skipped=%s warnings=%s",
                int((time.perf_counter() - product_apply_started) * 1000),
                len(plan.issues),
                len(apply_result.created_skus),
                len(apply_result.skipped_skus),
                len(apply_result.warnings),
            )
            inventory_service: InventoryService = self._container.resolve(InventoryService)
            print_report: StartExecutionReport | None = None
            required_print_skus = {
                decision.sku for decision in preflight.decisions if decision.will_print
            }
            if (
                mode == StartMode.INVOICES_AND_PRINT
                and not self._start_include_product_print
                and required_print_skus
            ):
                return {
                    "batch": {
                        "processed": 0,
                        "failures": 1,
                        "successful": 0,
                        "full_mode": True,
                        "print_products": False,
                        "aborted": False,
                    },
                    "inventory_report": None,
                    "inventory_warning": (
                        "START wurde vor der Rechnungsfinalisierung gestoppt, weil Bestand "
                        "fehlt. Bitte START + NOTENDRUCK verwenden: "
                        + ", ".join(sorted(required_print_skus))
                    ),
                    "product_apply": apply_result,
                }
            if mode == StartMode.INVOICES_AND_PRINT and self._start_include_product_print:
                print_report = inventory_service.execute_start_workflow(
                    preflight,
                    StartMode.PRINT_ONLY,
                )
                missing_prints = required_print_skus.difference(print_report.printed_skus)
                if missing_prints:
                    return {
                        "batch": {
                            "processed": 0,
                            "failures": 1,
                            "successful": 0,
                            "full_mode": True,
                            "print_products": True,
                            "aborted": False,
                        },
                        "inventory_report": print_report,
                        "inventory_warning": (
                            "START wurde vor der Rechnungsfinalisierung gestoppt, weil "
                            "erforderlicher Notendruck fehlgeschlagen ist: "
                            + ", ".join(sorted(missing_prints))
                        ),
                        "product_apply": apply_result,
                    }
            invoice_service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            batch_result = invoice_service.run_start_fullflow(
                full_mode=(mode == StartMode.INVOICES_AND_PRINT),
                print_products=self._start_include_product_print,
                should_abort=lambda: self._start_abort_requested,
                progress_callback=lambda message: signals.status_message.emit(message, 5000),
                invoice_ids=list(self._start_selected_invoice_ids) if self._start_selected_only else None,
            )
            inventory_report: StartExecutionReport | None = None
            inventory_warning = ""
            if mode == StartMode.INVOICES_AND_PRINT:
                if preflight.missing_position_data:
                    inventory_warning = (
                        "Inventar wurde nicht aktualisiert, weil kein Druckplan vorlag."
                    )
                elif bool(batch_result.get("failures")) or bool(batch_result.get("aborted")):
                    inventory_warning = (
                        "Inventar wurde nicht aktualisiert, weil der Lauf Fehler hatte "
                        "oder manuell gestoppt wurde."
                    )
                else:
                    inventory_report = inventory_service.execute_start_workflow(
                        preflight,
                        mode,
                        print_products=False,
                    )
                    if print_report is not None:
                        inventory_report = StartExecutionReport(
                            mode=inventory_report.mode,
                            open_invoice_count=inventory_report.open_invoice_count,
                            decisions_count=inventory_report.decisions_count,
                            printed_skus=list(print_report.printed_skus),
                            consumed_skus=list(inventory_report.consumed_skus),
                            stock_updated=(
                                print_report.stock_updated and inventory_report.stock_updated
                            ),
                            warnings=[
                                *print_report.warnings,
                                *inventory_report.warnings,
                            ],
                        )
            return {
                "batch": batch_result,
                "inventory_report": inventory_report,
                "inventory_warning": inventory_warning,
                "product_apply": apply_result,
            }

        self._start_exec_worker = BackgroundWorker(job)
        self._start_exec_worker.signals.result.connect(self._on_start_executed)
        self._start_exec_worker.signals.error.connect(self._on_start_preflight_error)
        self._start_exec_worker.signals.finished.connect(lambda: self._set_start_running(False))
        self._start_exec_worker.start()

    def _run_product_preflight_dialogs(self, plan: ProductPreflightPlan) -> dict[str, ProductIssueDecision]:
        decisions: dict[str, ProductIssueDecision] = {}
        for issue in plan.issues:
            dialog = ProductPreflightDialog(issue, part_categories=plan.part_categories, parent=self)
            decision = dialog.show_dialog()
            if decision is None:
                decision = ProductIssueDecision(action="skip", draft=issue.draft)
            decisions[issue.sku] = decision
        return decisions

    def _on_start_executed(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        self._pending_start_preflight = None
        batch = result.get("batch") if isinstance(result.get("batch"), dict) else result
        inventory_report = result.get("inventory_report")
        inventory_warning = str(result.get("inventory_warning") or "")
        product_apply = result.get("product_apply")

        processed = int(batch.get("processed") or 0)
        failures = int(batch.get("failures") or 0)
        successful = int(batch.get("successful") or max(0, processed - failures))
        full_mode = bool(batch.get("full_mode"))
        print_products = bool(batch.get("print_products"))
        aborted = bool(batch.get("aborted"))
        mode_label = StartMode.INVOICES_AND_PRINT.value if full_mode else StartMode.INVOICES_ONLY.value

        signals: AppSignals = self._container.resolve(AppSignals)
        if aborted:
            signals.status_message.emit(
                f"START gestoppt: {successful}/{processed} Rechnungen verarbeitet, Fehler: {failures}",
                5000,
            )
        else:
            signals.status_message.emit(
                f"START ausgefuehrt: {processed} Rechnungen ({mode_label}), Fehler: {failures}",
                5000,
            )

        lines = [
            f"Modus: {mode_label}",
            f"Notendruck: {'ja' if print_products else 'nein'}",
            f"Verarbeitete Rechnungen: {processed}",
            f"Erfolgreich: {successful}",
            f"Fehler: {failures}",
        ]
        if aborted:
            lines.append("Laufstatus: manuell gestoppt")
        if isinstance(inventory_report, StartExecutionReport):
            lines.append(
                f"Inventar aktualisiert: {'ja' if inventory_report.stock_updated else 'nein'}"
            )
            lines.append(
                f"Inventar-Druckjobs: {len(inventory_report.printed_skus)}"
            )
            if inventory_report.warnings:
                lines.append("Inventar-/Druck-Hinweise:")
                lines.extend(f"- {warning}" for warning in inventory_report.warnings)
        elif inventory_warning:
            lines.append(inventory_warning)
        if isinstance(product_apply, ProductPreflightApplyResult):
            if product_apply.created_skus:
                lines.append(f"Neue sevDesk-Produkte: {', '.join(product_apply.created_skus)}")
            if product_apply.warnings:
                lines.append("Produkt-Hinweise:")
                lines.extend(f"- {warning}" for warning in product_apply.warnings)

        if self._rechnungen_view is not None:
            self._rechnungen_view.show_start_summary(lines)

        if self._start_include_product_print:
            QMessageBox.information(
                self,
                "START abgeschlossen",
                "\n".join(lines),
            )

        if self._rechnungen_view is not None:
            self._rechnungen_view._reload_first_page()  # noqa: SLF001
        self._refresh_badges()

    def _on_start_preflight_error(self, exc: Exception) -> None:
        self._set_start_running(False)
        logger.error("Preflight failed: %s", exc)
        self._pending_start_preflight = None
        QMessageBox.warning(
            self,
            "Fehler",
            f"Pre-Flight konnte nicht erstellt werden:\n\n{exc}",
        )

    def _set_start_running(self, running: bool, *, allow_stop: bool = True) -> None:
        self._btn_start.setEnabled(not running)
        self._btn_start.setText("START..." if running else self._start_button_idle_text)
        self._btn_stop.setEnabled(bool(running and allow_stop))

    def _on_start_stop_clicked(self) -> None:
        running = any(
            worker is not None and worker.isRunning()
            for worker in (
                self._start_worker,
                self._start_product_worker,
                self._start_exec_worker,
            )
        )
        if not running and not self._btn_start.isEnabled():
            running = True
        if not running:
            return
        self._start_abort_requested = True
        self._btn_stop.setEnabled(False)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("STOP angefordert – aktueller Datensatz wird noch beendet…", 4000)

    def _on_reprints_clicked(self) -> None:
        """Trigger reprint preflight job for stock-up workflow."""
        if self._reprint_worker is not None and self._reprint_worker.isRunning():
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Nachdrucke Pre-Flight wird erstellt…", 2500)

        def job() -> ReprintPreflight:
            inventory_service: InventoryService = self._container.resolve(InventoryService)
            requirements = inventory_service.load_pending_requirements()
            return inventory_service.build_reprint_preflight(requirements)

        self._reprint_worker = BackgroundWorker(job)
        self._reprint_worker.signals.result.connect(self._on_reprint_preflight_ready)
        self._reprint_worker.signals.error.connect(self._on_reprint_error)
        self._reprint_worker.start()

    def _on_reprint_preflight_ready(self, result: object) -> None:
        """Show reprint preview dialog after preflight job completes."""
        if not isinstance(result, ReprintPreflight):
            return

        dlg = ReprintPreviewDialog(result, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if self._reprint_exec_worker is not None and self._reprint_exec_worker.isRunning():
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Nachdrucke werden ausgefuehrt…", 2500)

        def job() -> object:
            inventory_service: InventoryService = self._container.resolve(InventoryService)
            return inventory_service.execute_reprint_workflow(result)

        self._reprint_exec_worker = BackgroundWorker(job)
        self._reprint_exec_worker.signals.result.connect(self._on_reprint_executed)
        self._reprint_exec_worker.signals.error.connect(self._on_reprint_error)
        self._reprint_exec_worker.start()

    def _on_reprint_executed(self, result: object) -> None:
        """Show reprint execution summary and refresh UI."""
        if not isinstance(result, ReprintExecutionReport):
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(
            f"Nachdrucke ausgefuehrt: {result.decisions_count} Positionen geprüft, "
            f"{len(result.printed_skus)} SKUs zum Druck gegeben",
            5000,
        )

        QMessageBox.information(
            self,
            "Nachdrucke abgeschlossen",
            (
                f"Positionen geprüft: {result.decisions_count}\n"
                f"Druckjobs: {len(result.printed_skus)}\n"
                f"SKU: {', '.join(result.printed_skus) if result.printed_skus else 'keine'}\n"
                f"Bestand aktualisiert: {result.stock_updated}"
                + (
                    "\n\nHinweise:\n" + "\n".join(f"- {warning}" for warning in result.warnings)
                    if result.warnings
                    else ""
                )
            ),
        )

        self._refresh_badges()

    def _on_reprint_error(self, exc: Exception) -> None:
        """Handle reprint workflow errors."""
        logger.error("Reprint workflow failed: %s", exc)
        QMessageBox.warning(
            self,
            "Fehler",
            f"Nachdrucke-Workflow konnte nicht ausgefuehrt werden:\n\n{exc}",
        )

    def _on_beenden_clicked(self) -> None:
        """Gracefully shut down the application."""
        if self.has_active_flow():
            QMessageBox.warning(
                self,
                "App beenden",
                "Es laeuft noch ein Workflow. Bitte zuerst STOP bzw. den laufenden Flow abschliessen.",
            )
            return
        logger.info("User requested application shutdown via BEENDEN button.")
        window = self.window()
        if isinstance(window, QWidget):
            window.close()
            return
        QApplication.quit()
        running = any(
            w is not None and w.isRunning()
            for w in (
                self._badge_worker,
                self._start_worker,
                self._start_exec_worker,
                self._reprint_worker,
                self._reprint_exec_worker,
            )
        )
        if running:
            answer = QMessageBox.question(
                self,
                "App beenden",
                "Es laufen noch Hintergrundaufgaben.\n"
                "Trotzdem beenden? Laufende Operationen werden abgewartet (max. 5 s).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        else:
            answer = QMessageBox.question(
                self,
                "App beenden",
                "XW-Studio wirklich beenden?\n"
                "Alle Änderungen sind bereits in PostgreSQL gespeichert.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        logger.info("User requested application shutdown via BEENDEN button.")
        self._badge_timer.stop()
        self._wait_for_workers()
        QApplication.quit()
