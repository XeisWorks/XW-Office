"""FINANZEN > Ausgabenprüfung."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.commission.service import format_euro_amount
from xw_office.services.expenses.service import BankExpenseRow, ExpenseAuditService
from xw_office.ui.widgets.data_table import DataTable

if False:  # pragma: no cover
    from xw_office.core.container import Container


_HEADERS = ["Datum", "Empfänger", "Zahlungsreferenz / Verwendungszweck", "Betrag", "MusikHeroes", "Beleg"]


class ExpenseReviewView(QWidget):
    """Review outgoing XeisWorks transactions with profile-aware flags."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._rows: list[BankExpenseRow] = []
        self._start = QDateEdit()
        self._end = QDateEdit()
        self._status = QLabel("Noch nicht geladen")
        self._table = DataTable(_HEADERS)
        self._missing_table = DataTable(_HEADERS)
        self._build_ui()
        QTimer.singleShot(0, self._load)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Konto: XeisWorks"))
        controls.addWidget(QLabel("Von:"))
        self._start.setCalendarPopup(True)
        self._end.setCalendarPopup(True)
        today = datetime.now(tz=ZoneInfo("Europe/Vienna")).date()
        first = today.replace(day=1)
        previous_end = first - timedelta(days=1)
        self._start.setDate(previous_end.replace(day=1))
        self._end.setDate(previous_end)
        controls.addWidget(self._start)
        controls.addWidget(QLabel("Bis:"))
        controls.addWidget(self._end)
        reload_button = QPushButton("Neu laden")
        reload_button.clicked.connect(self._load)
        controls.addWidget(reload_button)
        controls.addStretch()
        root.addLayout(controls)
        root.addWidget(self._status)

        tabs = QTabWidget()
        tabs.addTab(self._build_bank_tab(), "Kontobewegungen")
        tabs.addTab(self._build_missing_tab(), "Fehlende Belege")
        root.addWidget(tabs, stretch=1)

    def _build_bank_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(lambda _index: self._open_selected(self._table))
        layout.addWidget(self._table, stretch=1)
        actions = QHBoxLayout()
        include = QPushButton("MusikHeroes einschließen")
        include.clicked.connect(lambda: self._flag_selected(True))
        exclude = QPushButton("MusikHeroes ausschließen")
        exclude.clicked.connect(lambda: self._flag_selected(False))
        actions.addWidget(include)
        actions.addWidget(exclude)
        actions.addStretch()
        layout.addLayout(actions)
        return page

    def _build_missing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._missing_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._missing_table.doubleClicked.connect(lambda _index: self._open_selected(self._missing_table))
        layout.addWidget(self._missing_table, stretch=1)
        return page

    def _load(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        start = self._start.date().toPython()
        end = self._end.date().toPython()
        service: ExpenseAuditService = self._container.resolve(ExpenseAuditService)
        self._status.setText("Bankbewegungen werden geladen …")
        self._worker = BackgroundWorker(
            lambda: service.list_bank_expenses(
                start=start, end=end, profile_key="musikheroes", refresh=True
            )
        )
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.start()

    def _on_loaded(self, payload: object) -> None:
        self._rows = [row for row in payload if isinstance(row, BankExpenseRow)] if isinstance(payload, list) else []
        self._populate(self._table, self._rows)
        # A concrete sevDesk document-link resolver will refine this projection;
        # until then every loaded outgoing payment is deliberately visible here.
        missing = [row for row in self._rows if row.document_link_scan_complete and not row.sevdesk_url]
        self._populate(self._missing_table, missing)
        incomplete = any(not row.document_link_scan_complete for row in self._rows)
        suffix = " · Belegscan unvollständig" if incomplete else ""
        self._status.setText(f"{len(self._rows)} ausgehende Zahlungen · Konto XeisWorks{suffix}")

    def _populate(self, table: DataTable, rows: list[BankExpenseRow]) -> None:
        table.set_data(
            [
                {
                    "Datum": row.value_date.strftime("%d.%m.%Y"),
                    "Empfänger": row.payee,
                    "Zahlungsreferenz / Verwendungszweck": row.purpose,
                    "Betrag": format_euro_amount(row.amount),
                    "MusikHeroes": row.profile_status or "—",
                    "Beleg": "sevDesk" if row.sevdesk_url else ("Lieferantenportal" if row.supplier_url else "fehlt"),
                    "__transaction_id": row.transaction_id,
                    "__iban": row.iban,
                    "__payee": row.payee,
                    "__sevdesk_url": row.sevdesk_url,
                    "__supplier_url": row.supplier_url,
                    "__align__Betrag": "right",
                }
                for row in rows
            ]
        )

    def _flag_selected(self, include: bool) -> None:
        selected = self._table.selected_row_data()
        if not selected:
            QMessageBox.information(self, "Ausgabenprüfung", "Bitte zuerst eine Kontobewegung auswählen.")
            return
        service: ExpenseAuditService = self._container.resolve(ExpenseAuditService)
        service.flag_profile_transaction(
            transaction_id=str(selected.get("__transaction_id") or ""),
            profile_key="musikheroes",
            payee=str(selected.get("__payee") or ""),
            iban=str(selected.get("__iban") or ""),
            include=include,
        )
        self._load()

    @staticmethod
    def _open_selected(table: DataTable) -> None:
        selected = table.selected_row_data()
        if not selected:
            return
        url = str(selected.get("__sevdesk_url") or selected.get("__supplier_url") or "").strip()
        if url.startswith("https://"):
            QDesktopServices.openUrl(QUrl(url))

    def _on_error(self, exc: Exception) -> None:
        self._status.setText("Abruf fehlgeschlagen")
        QMessageBox.warning(self, "Ausgabenprüfung", str(exc))
