"""Embedded Nachlieferungen tab for the OFFENE SENDUNGEN dashboard."""

from __future__ import annotations

import datetime
import json
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
from xw_office.services.sevdesk.invoice_client import InvoiceClient
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


class CustomerAftercareTab(QWidget):
    """All aftercare cases with source context, item editing and snooze actions."""

    def __init__(self, container: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: CustomerAftercareService = container.resolve(CustomerAftercareService)  # type: ignore[attr-defined]
        self._cases: list[CustomerAftercareCase] = []
        self._items: list[CustomerAftercareItem] = []
        self._invoice_worker: BackgroundWorker | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self._count = QLabel("-")
        top.addWidget(self._count, stretch=1)
        refresh = QPushButton("Aktualisieren")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
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
        for label, callback in (
            ("Bearbeiten…", self._edit),
            ("Originalrechnung anzeigen", self._show_invoice),
            ("Snoozen…", self._snooze),
            ("Sofort versenden", self._immediate),
            ("Erledigt", self._resolve),
            ("Stornieren", self._cancel),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch(1)
        detail_lay.addLayout(actions)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        root.addWidget(splitter)

    def refresh(self) -> None:
        selected_id = str(self._current().id) if self._current() is not None else ""
        self._cases = self._service.list_cases_for_filter("alle")
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

    def _current(self) -> CustomerAftercareCase | None:
        row = self._list.currentRow()
        return self._cases[row] if 0 <= row < len(self._cases) else None

    def _select(self, row: int) -> None:
        case = self._cases[row] if 0 <= row < len(self._cases) else None
        if case is None:
            self._items = []
            self._meta.setText("Keine Nachlieferung ausgewählt")
            self._positions.clear()
            self._mail.clear()
            self._ai.clear()
            return
        self._items = self._service.get_items(case.id)
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
        self._meta.setText(
            f"Kunde: {case.customer_name or case.customer_email or '—'}\n"
            f"Originalrechnung: {case.source_invoice_number or '—'} vom {case.source_invoice_date or '—'}\n"
            f"Wix-Bestellung: {case.source_wix_order_number or '—'}\n"
            f"Nachlieferung erstellt: {case.created_at:%d.%m.%Y %H:%M}\n"
            f"Fällig: {case.due_at.strftime('%d.%m.%Y %H:%M') if case.due_at else '—'}\n"
            f"Status: {_STATUS_LABELS.get(case.status, case.status)} | Snooze: {snooze}\n"
            f"Grund/Notiz: {case.snooze_reason or case.note or '—'}"
        )
        lines = []
        for item in self._items:
            marker = "✓" if item.role in {"MISSING_TO_SEND", "CORRECTED_ORDER_ITEM"} else "○"
            component = f" · Stimme/Komponente aus {item.parent_sku}" if item.parent_sku else ""
            lines.append(
                f"{marker} {item.quantity}× {item.name or item.sku} [{item.sku or 'ohne SKU'}]{component}"
            )
        self._positions.setPlainText("\n".join(lines) or "—")
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

    def _edit(self) -> None:
        case = self._current()
        if case is None:
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
        repo: CustomerAftercareRepository = self._container.resolve(CustomerAftercareRepository)  # type: ignore[attr-defined]
        repo.replace_items(case.id, outcome.items)
        repo.update_case_details(
            case.id,
            note=outcome.note,
            address_lines=outcome.address_lines,
            address_source="manual",
            shipping_mode=outcome.shipping_mode,
        )
        self._service.confirm_manual_redelivery(
            case.id, shipping_mode=outcome.shipping_mode, note=outcome.note
        )
        self.refresh()

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
        self._service.snooze_case(case.id, mode=mode, until=until, reason=reason)
        self.refresh()

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
            if isinstance(path, Path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

        worker = BackgroundWorker(job)
        worker.signals.result.connect(done)
        worker.signals.error.connect(
            lambda exc: QMessageBox.warning(
                self, "Originalrechnung", f"Rechnung konnte nicht geladen werden:\n\n{exc}"
            )
        )
        worker.signals.finished.connect(lambda: setattr(self, "_invoice_worker", None))
        self._invoice_worker = worker
        worker.start()

    def _immediate(self) -> None:
        case = self._current()
        if case is not None:
            self._service.make_immediate(case.id)
            self.refresh()

    def _resolve(self) -> None:
        case = self._current()
        if case is not None:
            self._service.mark_resolved(case.id)
            self.refresh()

    def _cancel(self) -> None:
        case = self._current()
        if case is not None:
            self._service.mark_cancelled(case.id)
            self.refresh()
