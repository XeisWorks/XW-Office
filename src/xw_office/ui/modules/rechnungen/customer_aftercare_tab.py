"""Embedded Nachlieferungen tab for the OFFENE SENDUNGEN dashboard."""

from __future__ import annotations

from collections.abc import Callable
import datetime
import json
import logging
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.repositories.customer_aftercare import CustomerAftercareRepository
from xw_office.services.customer_aftercare.service import CustomerAftercareService
from xw_office.services.printing.label_printer import LabelPrinter
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.sevdesk.invoice_client import InvoiceClient
from xw_office.services.sendungen.service import OffeneSendungenService, SendungProductLine
from xw_office.core.worker import BackgroundWorker
from xw_office.ui.modules.rechnungen.redelivery_dialog import RedeliveryDialog


_STATUS_LABELS = {
    "PENDING_REVIEW": "ZU PRÜFEN",
    "WAITING": "WARTET",
    "TRIGGERED": "FÄLLIG",
    "SNOOZED": "GESNOOZT",
    "RESOLVED": "ERLEDIGT",
    "CANCELLED": "STORNIERT",
    "IGNORED": "IGNORIERT",
}

logger = logging.getLogger(__name__)


class CustomerAftercareTab(QWidget):
    """All aftercare cases with source context, item editing and snooze actions."""

    def __init__(self, container: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_alive = True
        self.destroyed.connect(lambda *_args: setattr(self, "_ui_alive", False))
        self._container = container
        self._service: CustomerAftercareService | None = None
        self._cases: list[CustomerAftercareCase] = []
        self._items: list[CustomerAftercareItem] = []
        self._items_loaded_case_id = ""
        self._selection_seq = 0
        self._read_workers: list[BackgroundWorker] = []
        self._refresh_worker: BackgroundWorker | None = None
        self._refresh_pending = False
        self._case_action_worker: BackgroundWorker | None = None
        self._case_action_succeeded = False
        self._invoice_worker: BackgroundWorker | None = None
        self._dispatch_worker: BackgroundWorker | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self._count = QLabel("-")
        top.addWidget(self._count, stretch=1)
        self._refresh_button = QPushButton("Aktualisieren")
        self._refresh_button.clicked.connect(self.refresh)
        top.addWidget(self._refresh_button)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._select)
        splitter.addWidget(self._list)

        detail = QWidget()
        detail_lay = QVBoxLayout(detail)
        self._meta = QLabel("Keine Nachlieferung ausgewählt")
        self._meta.setWordWrap(True)
        self._meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_lay.addWidget(self._meta)
        detail_lay.addWidget(QLabel("Nachzuliefernde Positionen / Stimmen:"))
        self._positions = QPlainTextEdit()
        self._positions.setReadOnly(True)
        self._positions.setMaximumHeight(180)
        detail_lay.addWidget(self._positions)
        detail_lay.addWidget(QLabel("Originaler Mailtext:"))
        self._mail = QPlainTextEdit()
        self._mail.setReadOnly(True)
        detail_lay.addWidget(self._mail, stretch=1)
        self._ai = QLabel("")
        self._ai.setWordWrap(True)
        detail_lay.addWidget(self._ai)

        actions = QHBoxLayout()
        self._case_action_buttons: list[QPushButton] = []
        for label, callback in (
            ("Bearbeiten…", self._edit),
            ("Originalrechnung anzeigen", self._show_invoice),
            ("Snoozen…", self._snooze),
            ("Sofort versenden", self._immediate),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            self._case_action_buttons.append(button)
            actions.addWidget(button)
        actions.addStretch(1)
        detail_lay.addLayout(actions)

        dispatch_actions = QHBoxLayout()
        self._btn_delivery_show = QPushButton("Lieferschein zeigen")
        self._btn_delivery_show.setToolTip(
            "Erstellt den Lieferschein im selben Layout wie OFFENE SENDUNGEN"
        )
        self._btn_delivery_show.clicked.connect(self._show_delivery_note)
        dispatch_actions.addWidget(self._btn_delivery_show)
        self._btn_delivery_print = QPushButton("Lieferschein drucken")
        self._btn_delivery_print.setToolTip(
            "Druckt den Lieferschein über den Rechnungsdrucker"
        )
        self._btn_delivery_print.clicked.connect(self._print_delivery_note)
        dispatch_actions.addWidget(self._btn_delivery_print)
        self._btn_label_print = QPushButton("Label drucken")
        self._btn_label_print.setToolTip("Druckt ein Versandlabel mit der bestätigten Lieferadresse")
        self._btn_label_print.clicked.connect(self._print_label)
        dispatch_actions.addWidget(self._btn_label_print)
        dispatch_actions.addStretch(1)
        self._btn_resolve = QPushButton("Erledigt")
        self._btn_resolve.clicked.connect(self._resolve)
        self._case_action_buttons.append(self._btn_resolve)
        dispatch_actions.addWidget(self._btn_resolve)
        self._btn_cancel = QPushButton("Stornieren")
        self._btn_cancel.clicked.connect(self._cancel)
        self._case_action_buttons.append(self._btn_cancel)
        dispatch_actions.addWidget(self._btn_cancel)
        detail_lay.addLayout(dispatch_actions)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        root.addWidget(splitter)

    def refresh(self) -> None:
        current = self._current()
        selected_id = str(current.id) if current is not None else ""
        if self._case_action_worker is not None and self._case_action_worker.isRunning():
            self._refresh_pending = True
            return
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            self._refresh_pending = True
            return
        self._refresh_button.setEnabled(False)
        self._count.setText("Lade Nachlieferungen…")

        container = self._container
        current_service = self._service

        def job() -> tuple[CustomerAftercareService, list[CustomerAftercareCase]]:
            service: CustomerAftercareService = current_service or container.resolve(  # type: ignore[attr-defined]
                CustomerAftercareService
            )
            return service, service.list_cases_for_filter("alle")

        worker = BackgroundWorker(job)
        worker.signals.result.connect(
            lambda payload: self._on_cases_loaded(payload, selected_id)
            if self._ui_alive
            else None
        )
        worker.signals.error.connect(
            lambda exc: self._on_refresh_error(exc) if self._ui_alive else None
        )

        def finished(current_worker: BackgroundWorker = worker) -> None:
            if not self._ui_alive:
                return
            if self._refresh_worker is current_worker:
                self._refresh_worker = None
            self._refresh_button.setEnabled(True)
            if self._refresh_pending:
                self._refresh_pending = False
                self.refresh()

        worker.signals.finished.connect(finished)
        self._refresh_worker = worker
        self._track_read_worker(worker)
        worker.start()

    def _on_cases_loaded(self, payload: object, selected_id: str) -> None:
        if not self._ui_alive:
            return
        if not isinstance(payload, tuple) or len(payload) != 2:
            self._count.setText("Fehler: unerwartete Nachlieferungsdaten")
            self._set_case_actions_enabled(False)
            return
        service, cases = payload
        if not isinstance(cases, list) or not all(
            isinstance(case, CustomerAftercareCase) for case in cases
        ):
            self._count.setText("Fehler: unerwartete Nachlieferungsdaten")
            logger.error("Aftercare list worker returned invalid payload: %s", type(payload).__name__)
            self._set_case_actions_enabled(False)
            return
        self._service = service
        self._cases = cases
        self._list.clear()
        selected_row = -1
        for row, case in enumerate(self._cases):
            status = _STATUS_LABELS.get(case.status, case.status)
            refs = " / ".join(
                value
                for value in (case.source_invoice_number, case.source_wix_order_number)
                if value
            )
            label = f"[{status}] {case.customer_name or case.customer_email or 'Unbekannt'}"
            if refs:
                label += f" — {refs}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(case.id))
            self._list.addItem(item)
            if str(case.id) == selected_id:
                selected_row = row
        self._count.setText(f"{len(self._cases)} Nachlieferungen")
        if self._cases:
            self._list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        else:
            self._select(-1)

    def _on_refresh_error(self, exc: Exception) -> None:
        if not self._ui_alive:
            return
        self._count.setText(f"Laden fehlgeschlagen: {exc}")
        self._set_case_actions_enabled(False)

    def _track_read_worker(self, worker: BackgroundWorker) -> None:
        self._read_workers.append(worker)
        worker.signals.finished.connect(
            lambda current=worker: self._forget_read_worker(current)
        )

    def _require_service(self) -> CustomerAftercareService:
        service = self._service
        if service is None:
            raise RuntimeError("Lieferkorrektur-Service ist noch nicht geladen")
        return service

    def _forget_read_worker(self, worker: BackgroundWorker) -> None:
        if worker in self._read_workers:
            self._read_workers.remove(worker)

    def _set_case_actions_enabled(self, enabled: bool) -> None:
        action_enabled = enabled and not (
            self._case_action_worker is not None and self._case_action_worker.isRunning()
        )
        for button in self._case_action_buttons:
            button.setEnabled(action_enabled)
        self._update_dispatch_actions(self._current())

    def _run_case_action(self, label: str, job: Callable[[], object]) -> None:
        if self._case_action_worker is not None and self._case_action_worker.isRunning():
            return
        self._case_action_succeeded = False
        self._set_case_actions_enabled(False)
        self._refresh_button.setEnabled(False)
        self._count.setText(label)
        worker = BackgroundWorker(job)
        worker.signals.result.connect(self._on_case_action_result)
        worker.signals.error.connect(self._on_case_action_error)
        worker.signals.finished.connect(
            lambda current=worker: self._on_case_action_finished(current)
        )
        self._case_action_worker = worker
        self._track_read_worker(worker)
        worker.start()

    def _on_case_action_result(self, _payload: object) -> None:
        self._case_action_succeeded = True

    def _on_case_action_error(self, exc: Exception) -> None:
        if not self._ui_alive:
            return
        QMessageBox.warning(self, "Nachlieferung", f"Aktion fehlgeschlagen:\n\n{exc}")

    def _on_case_action_finished(self, worker: BackgroundWorker) -> None:
        if not self._ui_alive:
            return
        if self._case_action_worker is worker:
            self._case_action_worker = None
        self._refresh_button.setEnabled(
            self._refresh_worker is None or not self._refresh_worker.isRunning()
        )
        self._set_case_actions_enabled(self._items_loaded_case_id != "")
        if self._case_action_succeeded or self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    def _current(self) -> CustomerAftercareCase | None:
        row = self._list.currentRow()
        return self._cases[row] if 0 <= row < len(self._cases) else None

    def _select(self, row: int) -> None:
        self._selection_seq += 1
        seq = self._selection_seq
        case = self._cases[row] if 0 <= row < len(self._cases) else None
        if case is None:
            self._items = []
            self._items_loaded_case_id = ""
            self._meta.setText("Keine Nachlieferung ausgewählt")
            self._positions.clear()
            self._mail.clear()
            self._ai.clear()
            self._set_case_actions_enabled(False)
            self._update_dispatch_actions(None)
            return
        self._items = []
        self._items_loaded_case_id = ""
        self._positions.setPlainText("Positionen werden geladen…")
        self._set_case_actions_enabled(False)
        snooze = case.snooze_mode or "—"
        if case.snoozed_until:
            snoozed_until = case.snoozed_until
            if snoozed_until.tzinfo is None:
                snoozed_until = snoozed_until.replace(tzinfo=datetime.timezone.utc)
            snooze += (
                " bis "
                + snoozed_until.astimezone(ZoneInfo("Europe/Vienna")).strftime(
                    "%d.%m.%Y %H:%M"
                )
            )
        created_at = (
            case.created_at.strftime("%d.%m.%Y %H:%M") if case.created_at is not None else "—"
        )
        self._meta.setText(
            f"Kunde: {case.customer_name or case.customer_email or '—'}\n"
            f"Originalrechnung: {case.source_invoice_number or '—'} vom {case.source_invoice_date or '—'}\n"
            f"Wix-Bestellung: {case.source_wix_order_number or '—'}\n"
            f"Nachlieferung erstellt: {created_at}\n"
            f"Fällig: {case.due_at.strftime('%d.%m.%Y %H:%M') if case.due_at else '—'}\n"
            f"Status: {_STATUS_LABELS.get(case.status, case.status)} | Snooze: {snooze}\n"
            f"Grund/Notiz: {case.snooze_reason or case.note or '—'}"
        )
        self._mail.setPlainText(
            case.source_mail_body or "Keine Mailquelle – aus Rechnung erstellt."
        )
        try:
            payload = json.loads(case.ai_payload_json or "{}")
        except (TypeError, ValueError):
            payload = {}
        evidence = str(payload.get("evidence_quote") or "").strip()
        confidence = payload.get("confidence")
        self._ai.setText(
            f"OpenAI-Vorschlag: {confidence if confidence is not None else '—'}"
            + (f" · Belegstelle: „{evidence}“" if evidence else "")
        )
        self._update_dispatch_actions(case)
        case_id = case.id
        service = self._require_service()
        worker = BackgroundWorker(lambda: service.get_items(case_id))
        worker.signals.result.connect(
            lambda payload, selected_case_id=str(case_id), current_seq=seq: self._on_items_loaded(
                selected_case_id, current_seq, payload
            )
        )
        worker.signals.error.connect(
            lambda exc, current_seq=seq: self._on_items_error(current_seq, exc)
        )
        self._track_read_worker(worker)
        worker.start()

    def _on_items_loaded(self, case_id: str, seq: int, payload: object) -> None:
        if not self._ui_alive:
            return
        current = self._current()
        if (
            seq != self._selection_seq
            or current is None
            or str(current.id) != case_id
        ):
            return
        if not isinstance(payload, list) or not all(
            isinstance(item, CustomerAftercareItem) for item in payload
        ):
            self._items = []
            self._positions.setPlainText("Fehler: unerwartete Positionsdaten")
            logger.error("Aftercare items worker returned invalid payload: %s", type(payload).__name__)
            self._set_case_actions_enabled(False)
            return
        self._items = payload
        self._items_loaded_case_id = case_id
        lines = []
        for item in self._items:
            marker = "✓" if item.role in {"MISSING_TO_SEND", "CORRECTED_ORDER_ITEM"} else "○"
            component = f" · Stimme/Komponente aus {item.parent_sku}" if item.parent_sku else ""
            lines.append(
                f"{marker} {item.quantity}× {item.name or item.sku} [{item.sku or 'ohne SKU'}]{component}"
            )
        self._positions.setPlainText("\n".join(lines) or "—")
        self._set_case_actions_enabled(True)
        self._update_dispatch_actions(current)

    def _on_items_error(self, seq: int, exc: Exception) -> None:
        if not self._ui_alive:
            return
        if seq != self._selection_seq:
            return
        self._positions.setPlainText(f"Positionen konnten nicht geladen werden:\n{exc}")
        self._set_case_actions_enabled(False)

    def _update_dispatch_actions(self, case: CustomerAftercareCase | None) -> None:
        """Keep dispatch prints available only for a confirmed, active shipment."""
        enabled = bool(
            case is not None
            and case.status == "TRIGGERED"
            and str(case.dispatch_id or "").strip()
            and self._dispatch_worker is None
            and self._items_loaded_case_id == str(case.id)
            and not (
                self._case_action_worker is not None
                and self._case_action_worker.isRunning()
            )
        )
        for button in (
            self._btn_delivery_show,
            self._btn_delivery_print,
            self._btn_label_print,
        ):
            button.setEnabled(enabled)
        if case is None:
            tip = "Bitte zuerst eine Nachlieferung auswählen."
        elif case.status != "TRIGGERED" or not case.dispatch_id:
            tip = (
                "Zum Drucken die Positionen bestätigen und „Sofort versenden“ wählen "
                "bzw. die fällige Nachlieferung auslösen."
            )
        else:
            tip = ""
        for button in (
            self._btn_delivery_show,
            self._btn_delivery_print,
            self._btn_label_print,
        ):
            if tip:
                button.setToolTip(tip)
        if not tip:
            self._btn_delivery_show.setToolTip(
                "Erstellt den Lieferschein im selben Layout wie OFFENE SENDUNGEN"
            )
            self._btn_delivery_print.setToolTip(
                "Druckt den Lieferschein über den Rechnungsdrucker"
            )
            self._btn_label_print.setToolTip(
                "Druckt ein Versandlabel mit der bestätigten Lieferadresse"
            )

    def _dispatch_print_request(
        self,
    ) -> tuple[str, list[str], list[SendungProductLine], str] | None:
        """Build the current print payload from the confirmed aftercare case.

        The manual fields of the generated shipment are updated immediately
        before PDF/label generation.  Thus a later edit of the positions,
        address or note is reflected in the exact same print pipeline used by
        the OFFENE-SENDUNGEN tab.
        """
        case = self._current()
        if (
            case is None
            or case.status != "TRIGGERED"
            or not case.dispatch_id
            or self._items_loaded_case_id != str(case.id)
        ):
            QMessageBox.information(
                self,
                "Nachlieferung drucken",
                "Bitte die Nachlieferung zuerst aktivieren (Sofort versenden oder Fälligkeit).",
            )
            return None
        try:
            raw_address = json.loads(case.address_lines_json or "[]")
        except (TypeError, ValueError):
            raw_address = []
        address = (
            [str(line).strip() for line in raw_address if str(line).strip()]
            if isinstance(raw_address, list)
            else []
        )
        if not address:
            QMessageBox.information(
                self, "Nachlieferung drucken", "Keine zustellfähige Lieferadresse vorhanden."
            )
            return None
        products = [
            SendungProductLine(
                quantity=str(max(1, int(item.quantity or 1))),
                name=item.name or item.sku or "Nachlieferposition",
                sku=item.sku,
                note=item.note or "Nachlieferung – nicht verrechnen",
                free_delivery=True,
                no_return_required=True,
            )
            for item in self._items
            if item.role in {"MISSING_TO_SEND", "CORRECTED_ORDER_ITEM"}
        ]
        if not products:
            QMessageBox.information(
                self,
                "Nachlieferung drucken",
                "Bitte in „Bearbeiten…“ mindestens eine nachzuliefernde Position auswählen.",
            )
            return None
        return str(case.dispatch_id), address, products, case.note or ""

    def _run_dispatch_action(
        self,
        button: QPushButton,
        running_text: str,
        job: Callable[[], object],
        on_result: Callable[[object], object],
    ) -> None:
        if self._dispatch_worker is not None and self._dispatch_worker.isRunning():
            return
        original_text = button.text()
        for action in (
            self._btn_delivery_show,
            self._btn_delivery_print,
            self._btn_label_print,
        ):
            action.setEnabled(False)
        button.setText(running_text)
        worker = BackgroundWorker(job)
        worker.signals.result.connect(
            lambda payload: on_result(payload) if self._ui_alive else None
        )
        worker.signals.error.connect(
            lambda exc: self._on_dispatch_error(exc) if self._ui_alive else None
        )

        def finished() -> None:
            if not self._ui_alive:
                return
            button.setText(original_text)
            self._dispatch_worker = None
            self._update_dispatch_actions(self._current())

        worker.signals.finished.connect(finished)
        self._dispatch_worker = worker
        worker.start()

    def _on_dispatch_error(self, exc: Exception) -> None:
        if not self._ui_alive:
            return
        QMessageBox.warning(
            self, "Nachlieferung drucken", f"Druck konnte nicht vorbereitet werden:\n\n{exc}"
        )

    def _show_delivery_note(self) -> None:
        request = self._dispatch_print_request()
        if request is None:
            return
        dispatch_id, address, products, note = request
        sendungen: OffeneSendungenService = self._container.resolve(OffeneSendungenService)  # type: ignore[attr-defined]
        self._run_dispatch_action(
            self._btn_delivery_show,
            "Erstelle…",
            lambda: sendungen.generate_delivery_note_pdf(
                dispatch_id, address_lines=address, products=products, short_note=note
            ),
            lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))),
        )

    def _print_delivery_note(self) -> None:
        request = self._dispatch_print_request()
        if request is None:
            return
        dispatch_id, address, products, note = request
        sendungen: OffeneSendungenService = self._container.resolve(OffeneSendungenService)  # type: ignore[attr-defined]

        def job() -> Path:
            path = sendungen.generate_delivery_note_pdf(
                dispatch_id, address_lines=address, products=products, short_note=note
            )
            sendungen.print_delivery_note(
                path,
                printing=self._container.config.printing,  # type: ignore[attr-defined]
                print_queue=self._container.resolve(PrintQueueService),  # type: ignore[attr-defined]
            )
            return path

        self._run_dispatch_action(
            self._btn_delivery_print,
            "Drucke…",
            job,
            lambda _path: QMessageBox.information(
                self, "Lieferschein", "Lieferschein erfolgreich an Rechnungen gesendet."
            ),
        )

    def _print_label(self) -> None:
        request = self._dispatch_print_request()
        if request is None:
            return
        dispatch_id, address, products, note = request
        sendungen: OffeneSendungenService = self._container.resolve(OffeneSendungenService)  # type: ignore[attr-defined]

        def job() -> bool:
            sendungen.save_manual_fields(
                dispatch_id, address_lines=address, products=products, manual_text=note
            )
            printer = LabelPrinter(
                self._container.config.printing,  # type: ignore[attr-defined]
                print_queue=self._container.resolve(PrintQueueService),  # type: ignore[attr-defined]
            )
            printer.print_address(address)
            return True

        self._run_dispatch_action(
            self._btn_label_print,
            "Drucke…",
            job,
            lambda _payload: QMessageBox.information(
                self, "Label", "Label erfolgreich an Drucker gesendet."
            ),
        )

    def _edit(self) -> None:
        case = self._current()
        if case is None or self._items_loaded_case_id != str(case.id):
            return
        try:
            address = json.loads(case.address_lines_json or "[]")
        except (TypeError, ValueError):
            address = []
        dialog = RedeliveryDialog(
            case,
            self._items,
            address_lines=address if isinstance(address, list) else [],
            address_source=case.address_source,
            parent=self,
        )
        dialog.exec()
        outcome = dialog.outcome()
        if outcome is None:
            return
        case_id = case.id
        repo: CustomerAftercareRepository = self._container.resolve(CustomerAftercareRepository)  # type: ignore[attr-defined]

        def save() -> object:
            repo.replace_items(case_id, outcome.items)
            repo.update_case_details(
                case_id,
                note=outcome.note,
                address_lines=outcome.address_lines,
                address_source="manual",
                shipping_mode=outcome.shipping_mode,
            )
            return self._require_service().confirm_manual_redelivery(
                case_id, shipping_mode=outcome.shipping_mode, note=outcome.note
            )

        self._run_case_action("Speichere Nachlieferung…", save)

    def _snooze(self) -> None:
        case = self._current()
        if case is None:
            return
        labels = [
            "Bis zum nächsten START-Lauf",
            "Bis zur nächsten Bestellung dieses Kunden",
            "Bis Datum/Uhrzeit",
        ]
        choice, ok = QInputDialog.getItem(
            self, "Nachlieferung snoozen", "Snooze:", labels, 0, False
        )
        if not ok:
            return
        mode = "NEXT_START"
        until = None
        if choice == labels[1]:
            mode = "NEXT_ORDER"
        elif choice == labels[2]:
            mode = "UNTIL_DATE"
            default = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime(
                "%d.%m.%Y %H:%M"
            )
            value, accepted = QInputDialog.getText(
                self, "Snooze bis", "Datum/Uhrzeit (TT.MM.JJJJ HH:MM):", text=default
            )
            if not accepted:
                return
            try:
                local = datetime.datetime.strptime(value.strip(), "%d.%m.%Y %H:%M").replace(
                    tzinfo=ZoneInfo("Europe/Vienna")
                )
                until = local.astimezone(datetime.timezone.utc)
            except ValueError:
                QMessageBox.warning(self, "Snooze", "Bitte Datum als TT.MM.JJJJ HH:MM eingeben.")
                return
        reason, accepted = QInputDialog.getText(self, "Snooze-Grund", "Grund (optional):")
        if not accepted:
            return
        case_id = case.id
        self._run_case_action(
            "Snooze wird gespeichert…",
            lambda: self._require_service().snooze_case(
                case_id, mode=mode, until=until, reason=reason
            ),
        )

    def _show_invoice(self) -> None:
        case = self._current()
        if case is None or not case.source_invoice_id:
            QMessageBox.information(self, "Originalrechnung", "Keine sevDesk-Rechnung verknüpft.")
            return
        if self._invoice_worker is not None and self._invoice_worker.isRunning():
            return
        invoice_id = case.source_invoice_id
        invoice_number = case.source_invoice_number or invoice_id

        def job() -> Path:
            client: InvoiceClient = self._container.resolve(InvoiceClient)  # type: ignore[attr-defined]
            payload = client.get_invoice_pdf(invoice_id)
            safe_number = re.sub(r"[^A-Za-z0-9._-]+", "-", invoice_number)
            target = Path(tempfile.gettempdir()) / f"xw-originalrechnung-{safe_number}.pdf"
            target.write_bytes(payload)
            return target

        def done(path: object) -> None:
            if self._ui_alive and isinstance(path, Path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

        worker = BackgroundWorker(job)
        worker.signals.result.connect(done)
        worker.signals.error.connect(
            lambda exc: self._on_invoice_error(exc) if self._ui_alive else None
        )
        worker.signals.finished.connect(lambda: setattr(self, "_invoice_worker", None))
        self._invoice_worker = worker
        worker.start()

    def _on_invoice_error(self, exc: Exception) -> None:
        if not self._ui_alive:
            return
        QMessageBox.warning(
            self, "Originalrechnung", f"Rechnung konnte nicht geladen werden:\n\n{exc}"
        )

    def _immediate(self) -> None:
        case = self._current()
        if case is not None:
            case_id = case.id
            self._run_case_action(
                "Nachlieferung wird ausgelöst…",
                lambda: self._require_service().make_immediate(case_id),
            )

    def _resolve(self) -> None:
        case = self._current()
        if case is not None:
            case_id = case.id
            self._run_case_action(
                "Erledigung wird gespeichert…",
                lambda: self._require_service().mark_resolved(case_id),
            )

    def _cancel(self) -> None:
        case = self._current()
        if case is not None:
            case_id = case.id
            self._run_case_action(
                "Stornierung wird gespeichert…",
                lambda: self._require_service().mark_cancelled(case_id),
            )
