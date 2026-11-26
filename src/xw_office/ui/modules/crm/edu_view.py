"""EDU school, membership and approval management in the CRM."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.crm.edu_client import EduClient

_FIELDS = (
    ("institutionName", "Einrichtung"),
    ("billingEntityName", "Rechnungsempfänger / Träger"),
    ("directorName", "Direktion"),
    ("addressLine1", "Rechnungsstraße"),
    ("addressLine2", "Adresszusatz"),
    ("postalCode", "Postleitzahl"),
    ("city", "Ort"),
    ("country", "Land (ISO 2)"),
    ("subdivision", "Region"),
    ("billingEmail", "Rechnungs- und Mahn-Mail"),
    ("billingCcEmail", "Rechnungskopie"),
    ("sevdeskContactId", "sevDesk-Organisations-ID"),
)
_STATE_LABELS = {
    "active": "Aktiv",
    "pending": "Offen",
    "verified": "Freigegeben",
    "blocked": "Gesperrt",
    "revoked": "Widerrufen",
    "sent": "Versendet",
    "failed": "Fehlgeschlagen",
    "attempted": "Prüfung nötig",
    "applied": "Gespeichert",
}


class EduView(QWidget):
    def __init__(self, client: EduClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._worker: BackgroundWorker | None = None
        self._school: dict[str, Any] = {}
        self._order_rows: list[dict[str, Any]] = []
        self._rows: dict[str, list[dict[str, Any]]] = {}
        self._retry: dict[str, Any] | None = None
        self._result: Any = None
        self._error: Exception | None = None
        self._on_success: Callable[[Any], None] | None = None
        self._started = False

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._schools = QComboBox()
        self._schools.setEditable(True)
        self._schools.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._schools.activated.connect(self._load_school)
        bar.addWidget(QLabel("Einrichtung"))
        bar.addWidget(self._schools, 1)
        self._reload = QPushButton("Aktualisieren")
        self._reload.clicked.connect(self._load_list)
        bar.addWidget(self._reload)
        self._retry_button = QPushButton("Letzten Auftrag wiederholen")
        self._retry_button.clicked.connect(self._retry_update)
        self._retry_button.setEnabled(False)
        bar.addWidget(self._retry_button)
        root.addLayout(bar)
        self._status = QLabel()
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        self._tabs = QTabWidget()
        self._tabs.setEnabled(False)
        root.addWidget(self._tabs, 1)
        school_page = QWidget()
        school_layout = QVBoxLayout(school_page)
        self._school_status = QLabel()
        self._school_status.setTextFormat(Qt.TextFormat.PlainText)
        self._school_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        school_layout.addWidget(self._school_status)
        form = QFormLayout()
        self._fields: dict[str, QLineEdit] = {}
        for field, label in _FIELDS:
            editor = QLineEdit()
            self._fields[field] = editor
            form.addRow(label, editor)
        school_layout.addLayout(form)
        self._add_actions(
            school_layout,
            "school",
            (
                ("Speichern", "edit"),
                ("Schule freigeben", "approve"),
                ("Sperren", "block"),
                ("Zur Prüfung öffnen", "reopen"),
                ("Bestätigung an Rechnungs-Mail senden", "sendBillingMail"),
            ),
        )
        school_layout.addStretch()
        self._tabs.addTab(school_page, "Stammdaten")

        self._teachers = self._add_table(
            "Lehrkräfte",
            [
                "Name",
                "Zuordnung",
                "Globaler Status",
                "Primärschule",
                "Wix-Mitglieds-ID",
                "Wix-Kontakt-ID",
            ],
            "teacherLink",
            (
                ("Zuordnung freigeben / reaktivieren", "approve"),
                ("Zuordnung sperren", "block"),
                ("Global freigeben", "verifyTeacher"),
                ("Global sperren", "blockTeacher"),
                ("Global zur Prüfung öffnen", "reopenTeacher"),
            ),
        )
        self._admins = self._add_table(
            "Vertretungen",
            ["Name", "Status", "Rechnungskauf", "Wix-Mitglieds-ID", "Wix-Kontakt-ID"],
            "adminLink",
            (
                ("Freigeben", "approve"),
                ("Widerrufen", "revoke"),
                ("Zur Prüfung öffnen", "reopen"),
                ("Vertretungsmail senden", "sendRepresentativeMail"),
                ("Rechnungskauf freigeben", "grantOrder"),
                ("Rechnungskauf entziehen", "revokeOrder"),
            ),
        )
        self._invites = self._add_table(
            "Mails", ["Vorgang", "Empfänger", "Versand", "Bestätigt", "Gültig bis"]
        )
        self._history = self._add_table(
            "Verlauf", ["Zeit", "Aktion", "Ziel", "Status", "Ausgelöst von", "Änderung"]
        )
        retry_order = QPushButton("Ausgewählten Sync-Vorgang wiederholen")
        retry_order.clicked.connect(self._retry_order)
        self._orders = self._add_table(
            "Rechnungssync",
            ["Wix-Auftrag", "Status", "Grund", "sevDesk-Kontakt-ID", "sevDesk-Beleg-ID"],
            footer=retry_order,
        )

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._load_list()

    def _add_actions(
        self, layout: QVBoxLayout, target: str, actions: Sequence[tuple[str, str]]
    ) -> None:
        row = QHBoxLayout()
        for label, action in actions:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, task=action: self._update(target, task))
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)

    def _add_table(
        self,
        label: str,
        columns: list[str],
        target: str = "",
        actions: Sequence[tuple[str, str]] = (),
        footer: QWidget | None = None,
    ) -> QTableWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        if actions:
            self._add_actions(layout, target, actions)
        if footer is not None:
            layout.addWidget(footer)
        self._tabs.addTab(page, label)
        return table

    def _run(self, job: Callable[[], Any], success: Callable[[Any], None]) -> None:
        if self._worker is not None:
            return
        self._status.setText("EDU-Daten werden geladen …")
        self._set_busy(True)
        worker = BackgroundWorker(job)
        self._worker = worker
        self._result = None
        self._error = None
        worker.signals.result.connect(self._store_result)
        worker.signals.error.connect(self._store_error)
        self._on_success = success
        worker.signals.finished.connect(self._finish)
        worker.start()

    def _store_result(self, result: object) -> None:
        self._result = result

    def _store_error(self, error: Exception) -> None:
        self._error = error

    def _finish(self) -> None:
        self._worker = None
        success, self._on_success = self._on_success, None
        self._set_busy(False)
        if self._error is not None:
            self._status.setText(str(self._error))
            return
        self._status.setText("Mit Wix verbunden")
        if success is not None:
            success(self._result)

    def _set_busy(self, busy: bool) -> None:
        self._schools.setEnabled(not busy)
        self._reload.setEnabled(not busy)
        self._retry_button.setEnabled(not busy and self._retry is not None)
        self._tabs.setEnabled(not busy and bool(self._school))

    def _load_list(self) -> None:
        selected = self._schools.currentData()

        def show(result: dict[str, Any]) -> None:
            self._schools.clear()
            for item in result["schools"]:
                self._schools.addItem(
                    f"{item['institutionName']} · {item.get('city', '')}", item["id"]
                )
            index = self._schools.findData(selected)
            self._schools.setCurrentIndex(index if index >= 0 else 0)
            if self._schools.count():
                self._load_school()
            else:
                self._school = {}
                self._tabs.setEnabled(False)
                self._status.setText("Keine EDU-Einrichtungen vorhanden.")

        self._run(lambda: self._client.command("list"), show)

    def _load_school(self) -> None:
        institution_id = self._schools.currentData()
        if institution_id:
            self._school = {}

            def read() -> dict[str, Any]:
                result = self._client.command("detail", institutionId=institution_id)
                try:
                    result["orders"] = self._client.school_orders(institution_id)
                except (RuntimeError, OSError, ValueError) as error:
                    result["sync_error"] = str(error)
                return result

            self._run(read, self._show_school)

    @staticmethod
    def _fill(table: QTableWidget, rows: Iterable[Sequence[object]]) -> None:
        table.setRowCount(0)
        for values in rows:
            row = table.rowCount()
            table.insertRow(row)
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value or "")))

    def _show_school(self, data: dict[str, Any]) -> None:
        self._school = school = data["school"]
        self._tabs.setEnabled(True)
        state = _STATE_LABELS.get(school["status"], school["status"])
        mail = "bestätigt" if school["mailConfirmed"] else "offen"
        self._school_status.setText(
            f"Schule {state} · Rechnungs-Mail {mail} · Wix-ID {school['id']}"
        )
        for field, editor in self._fields.items():
            editor.setText(school.get(field, ""))
        self._rows = {"teacherLink": data["teachers"], "adminLink": data["admins"]}
        self._fill(
            self._teachers,
            (
                (
                    row["name"],
                    _STATE_LABELS.get(row["status"], row["status"]),
                    _STATE_LABELS.get(row.get("globalStatus"), ""),
                    "Ja" if row["primary"] else "",
                    row["memberId"],
                    row.get("wixContactId"),
                )
                for row in data["teachers"]
            ),
        )
        self._fill(
            self._admins,
            (
                (
                    row["name"],
                    _STATE_LABELS.get(row["status"], row["status"]),
                    "Freigegeben" if row["canOrderOnInvoice"] else "",
                    row["memberId"],
                    row.get("wixContactId"),
                )
                for row in data["admins"]
            ),
        )
        self._fill(
            self._invites,
            (
                (
                    row.get("kind"),
                    row["recipient"],
                    _STATE_LABELS.get(row["status"], row["status"]),
                    row.get("confirmedAt"),
                    row.get("expiresAt"),
                )
                for row in data["invitations"]
            ),
        )
        self._order_rows = data.get("orders", [])
        self._fill(
            self._orders,
            (
                (
                    row["number"],
                    row["status"],
                    row["state_reason"],
                    row["sevdesk_contact_id"],
                    row["sevdesk_invoice_id"],
                )
                for row in self._order_rows
            ),
        )
        if "sync_error" in data:
            self._status.setText("Wix verbunden. " + data["sync_error"])
        self._fill(
            self._history,
            (
                (
                    row.get("_createdDate"),
                    row["action"],
                    row["targetId"],
                    _STATE_LABELS.get(row["status"], row["status"]),
                    row["actor"],
                    json.dumps(row["after"], ensure_ascii=False),
                )
                for row in data["history"]
            ),
        )

    def _retry_order(self) -> None:
        row = self._orders.currentRow()
        if row < 0:
            self._status.setText("Bitte wähle einen Sync-Vorgang aus.")
            return
        order = self._order_rows[row]
        if order["status"] not in {"failed", "dead_letter", "awaiting_wix"}:
            self._status.setText("Dieser Status erfordert keine automatische Wiederholung.")
            return
        if (
            QMessageBox.question(
                self, "Rechnungssync", "Soll der Vorgang erneut zur Verarbeitung eingereiht werden?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        institution_id = self._school["id"]
        self._run(
            lambda: self._client.retry_school_order(institution_id, order["id"]),
            lambda _result: self._load_school(),
        )

    def _update(self, target: str, action: str) -> None:
        if not self._school:
            return
        row = self._school
        if target != "school":
            table = self._teachers if target == "teacherLink" else self._admins
            index = table.currentRow()
            if index < 0:
                self._status.setText("Bitte wähle zuerst einen Eintrag aus.")
                return
            row = self._rows[target][index]
        fields = (
            {key: widget.text().strip() for key, widget in self._fields.items()}
            if action == "edit"
            else {}
        )
        if (
            action.startswith("send")
            and QMessageBox.question(
                self,
                "EDU-Mail",
                "Soll die Bestätigung jetzt an die hinterlegte Schuladresse gesendet werden?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._retry = dict(
            target=target,
            action=action,
            institutionId=self._school["id"],
            targetId=row["id"],
            version=row["version"],
            profileVersion=row.get("profileVersion"),
            requestId=uuid4().hex,
            fields=fields,
        )
        self._retry_update()

    def _retry_update(self) -> None:
        if self._retry is None:
            return
        command = dict(self._retry)
        self._run(lambda: self._client.command("update", **command), self._after_update)

    def _after_update(self, result: dict[str, Any]) -> None:
        self._retry = None
        self._retry_button.setEnabled(False)
        delivery = result.get("delivery")
        if delivery and delivery != "sent":
            QMessageBox.information(
                self,
                "EDU-Mail",
                "Der Versand ist noch offen. Prüfe den Mailstatus und die Konfiguration.",
            )
        self._load_school()
