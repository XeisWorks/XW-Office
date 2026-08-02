"""CRM module — live contacts from sevDesk with duplicate scan."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.crm import ContactRecord, CrmService, MergeResult
from xw_office.services.crm.types import DuplicateCandidate
from xw_office.ui.widgets.data_table import DataTable
from xw_office.ui.widgets.search_bar import SearchBar

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)

_HEADERS = ["Score", "Kontakt A", "Kontakt B", "E-Mail A", "E-Mail B"]

_DEMO_CONTACTS: list[ContactRecord] = [
    ContactRecord(id="1", name="Musik Verlag Nord", email="kontakt@mv-nord.test"),
    ContactRecord(id="2", name="Verlags Nord GmbH", email="kontakt@mv-nord.test"),
    ContactRecord(id="3", name="Klavierschule Sued", email="info@klavier-sued.test"),
    ContactRecord(id="4", name="Klavierschule Süd", email="info@klavier-sued.test"),
]


class _MergeWizardDialog(QDialog):
    """Simple master/duplicate chooser for CRM merge."""

    def __init__(self, candidate: DuplicateCandidate, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._candidate = candidate
        self.setWindowTitle("Duplikat zusammenfuehren")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        intro = QLabel("Waehle den Hauptkontakt (Master), der erhalten bleiben soll.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        group = QGroupBox("Master-Auswahl")
        g_lay = QVBoxLayout(group)
        self._a_btn = QPushButton(self._label_for(candidate.a))
        self._a_btn.setCheckable(True)
        self._a_btn.setChecked(True)
        self._b_btn = QPushButton(self._label_for(candidate.b))
        self._b_btn.setCheckable(True)
        self._a_btn.toggled.connect(lambda checked: self._b_btn.setChecked(not checked) if checked else None)
        self._b_btn.toggled.connect(lambda checked: self._a_btn.setChecked(not checked) if checked else None)
        g_lay.addWidget(self._a_btn)
        g_lay.addWidget(self._b_btn)
        layout.addWidget(group)

        note = QLabel(
            "Feldregel: Name/E-Mail/Telefon/Stadt bleiben beim Master, "
            "fehlende Felder werden vom Duplikat ergaenzt."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _label_for(row: ContactRecord) -> str:
        return f"{row.name}  ({row.email or 'keine E-Mail'})"

    @property
    def master(self) -> ContactRecord:
        return self._candidate.a if self._a_btn.isChecked() else self._candidate.b

    @property
    def duplicate(self) -> ContactRecord:
        return self._candidate.b if self._a_btn.isChecked() else self._candidate.a


class CrmView(QWidget):
    """Customer maintenance with live sevDesk contact sync and duplicate detection."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._contacts: list[ContactRecord] = []
        self._dup_candidates: list[DuplicateCandidate] = []
        self._worker: BackgroundWorker | None = None
        self._pending_merge_pair: tuple[ContactRecord, ContactRecord] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # --- header bar ---
        bar = QHBoxLayout()
        crm: CrmService = container.resolve(CrmService)
        self._status_lbl = QLabel(
            "Live: sevDesk verbunden — Kontakte laden…"
            if crm.has_live_connection()
            else "Demo-Modus (kein sevDesk-Token). Ergebnisse sind Testdaten."
        )
        self._status_lbl.setObjectName("crmStatusLabel")
        bar.addWidget(self._status_lbl)
        bar.addStretch()
        self._sync_btn = QPushButton("Kontakte laden")
        self._sync_btn.clicked.connect(self._load_contacts)
        bar.addWidget(self._sync_btn)
        root.addLayout(bar)

        # --- search bar ---
        search_row = QHBoxLayout()
        self._search = SearchBar("Kontakte filtern (mind. 3 Zeichen)…")
        self._search.setPlaceholderText("Kontakte filtern…")
        self._search.search_changed.connect(self._apply_filter)
        self._search.set_suggestion_provider(self._contact_search_suggestions)
        search_row.addWidget(self._search)
        self._scan_btn = QPushButton("Duplikat-Scan")
        self._scan_btn.clicked.connect(self._run_scan)
        search_row.addWidget(self._scan_btn)
        self._merge_btn = QPushButton("Merge-Wizard")
        self._merge_btn.clicked.connect(self._open_merge_wizard)
        self._merge_btn.setEnabled(False)
        search_row.addWidget(self._merge_btn)
        root.addLayout(search_row)

        # --- contacts table ---
        contact_lbl = QLabel("Kontakte")
        contact_lbl.setObjectName("sectionLabel")
        root.addWidget(contact_lbl)

        self._contacts_table = DataTable(["ID", "Name", "E-Mail", "Telefon"])
        self._contacts_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._contacts_table, stretch=3)

        # --- duplicates table ---
        dup_lbl = QLabel("Mögliche Duplikate")
        dup_lbl.setObjectName("sectionLabel")
        root.addWidget(dup_lbl)

        self._dup_table = DataTable(_HEADERS)
        self._dup_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        root.addWidget(self._dup_table, stretch=2)

        # --- auto-load contacts on show ---
        self._load_contacts()

    # ------------------------------------------------------------------
    # Contact loading
    # ------------------------------------------------------------------

    def _load_contacts(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        crm: CrmService = self._container.resolve(CrmService)
        self._sync_btn.setEnabled(False)
        self._status_lbl.setText("Laden…")

        def job() -> list[ContactRecord]:
            if crm.has_live_connection():
                return cast("list[ContactRecord]", crm.fetch_live_contacts())
            return list(_DEMO_CONTACTS)

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_contacts_loaded)
        self._worker.signals.error.connect(self._on_load_error)
        self._worker.start()

    def _on_contacts_loaded(self, contacts: object) -> None:
        if not isinstance(contacts, list):
            return
        self._contacts = [row for row in contacts if isinstance(row, ContactRecord)]
        crm: CrmService = self._container.resolve(CrmService)
        src = "sevDesk" if crm.has_live_connection() else "Demo"
        self._status_lbl.setText(f"{len(self._contacts)} Kontakte geladen ({src})")
        self._sync_btn.setEnabled(True)
        self._search.refresh_suggestions()
        self._populate_contacts_table(self._contacts)

    def _on_load_error(self, exc: BaseException) -> None:
        self._sync_btn.setEnabled(True)
        self._status_lbl.setText(f"Fehler: {exc}")
        logger.exception("CRM contact load failed: %s", exc)

    # ------------------------------------------------------------------
    # Contacts table population & filtering
    # ------------------------------------------------------------------

    def _populate_contacts_table(self, rows: list[ContactRecord]) -> None:
        self._contacts_table.set_data(
            [
                {
                    "ID": rec.id,
                    "Name": rec.name,
                    "E-Mail": rec.email or "",
                    "Telefon": rec.phone or "",
                    "__record__": rec,
                }
                for rec in rows
            ]
        )

    def _apply_filter(self, text: str) -> None:
        needle = text.lower()
        filtered = [
            r for r in self._contacts
            if needle in (r.name or "").lower()
            or needle in (r.email or "").lower()
        ]
        self._populate_contacts_table(filtered)

    def _contact_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 3:
            return []
        out: list[str] = []
        for row in self._contacts:
            hay = f"{row.name} {row.email or ''} {row.phone or ''}".lower()
            if q in hay:
                out.append(f"{row.name} ({row.email or 'keine E-Mail'})")
        return out

    # ------------------------------------------------------------------
    # Duplicate scan
    # ------------------------------------------------------------------

    def _run_scan(self) -> None:
        if not self._contacts:
            QMessageBox.information(self, "CRM", "Bitte zuerst Kontakte laden.")
            return
        crm: CrmService = self._container.resolve(CrmService)
        self._scan_btn.setEnabled(False)

        contacts_snapshot = list(self._contacts)

        def job() -> list[DuplicateCandidate]:
            return cast("list[DuplicateCandidate]", crm.find_duplicates_in_memory(contacts_snapshot))

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_scan_done)
        self._worker.signals.error.connect(self._on_scan_error)
        self._worker.start()

    def _on_scan_done(self, dups: object) -> None:
        self._scan_btn.setEnabled(True)
        if not isinstance(dups, list):
            return
        self._dup_candidates = [d for d in dups if isinstance(d, DuplicateCandidate)]
        self._merge_btn.setEnabled(bool(self._dup_candidates))
        table_rows: list[dict[str, object]] = []
        for dup in dups:
            if not isinstance(dup, DuplicateCandidate):
                continue
            table_rows.append(
                {
                    "Score": str(dup.score),
                    "Kontakt A": dup.a.name,
                    "Kontakt B": dup.b.name,
                    "E-Mail A": dup.a.email or "",
                    "E-Mail B": dup.b.email or "",
                    "__sort__Score": dup.score,
                    "__align__Score": "center",
                    "__candidate__": dup,
                }
            )
        self._dup_table.set_data(table_rows)
        if not dups:
            QMessageBox.information(
                self, "CRM", "Keine Duplikate über dem Schwellwert gefunden."
            )

    def _on_scan_error(self, exc: Exception) -> None:
        self._scan_btn.setEnabled(True)
        self._status_lbl.setText(f"Duplikat-Scan fehlgeschlagen: {exc}")
        QMessageBox.warning(self, "CRM", str(exc))

    def _open_merge_wizard(self) -> None:
        row = self._dup_table.selected_row_data() or {}
        candidate = row.get("__candidate__")
        if not isinstance(candidate, DuplicateCandidate):
            QMessageBox.information(self, "CRM", "Bitte zuerst ein Duplikat in der Tabelle waehlen.")
            return
        dlg = _MergeWizardDialog(candidate, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        crm: CrmService = self._container.resolve(CrmService)
        self._merge_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._sync_btn.setEnabled(False)
        self._status_lbl.setText("Merge wird ausgefuehrt...")
        self._pending_merge_pair = (dlg.master, dlg.duplicate)

        def job() -> MergeResult:
            return crm.merge_contacts(dlg.master, dlg.duplicate)

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_merge_done)
        self._worker.signals.error.connect(self._on_merge_error)
        self._worker.start()

    def _on_merge_done(self, result: object) -> None:
        if not isinstance(result, MergeResult):
            return
        updated: list[ContactRecord] = []
        for row in self._contacts:
            if row.id in (result.master_id, result.duplicate_id):
                continue
            updated.append(row)
        updated.append(result.merged)
        self._contacts = updated
        self._populate_contacts_table(self._contacts)
        self._status_lbl.setText("Merge abgeschlossen")
        self._sync_btn.setEnabled(True)
        self._scan_btn.setEnabled(True)
        self._run_scan()

        QMessageBox.information(
            self,
            "CRM Merge",
            (
                f"Duplikat zusammengefuehrt.\n"
                f"Master: {result.master_id}\n"
                f"Entfernt: {result.duplicate_id}\n"
                "Aenderungen wurden bei Live-Verbindung zu sevDesk geschrieben."
            ),
        )

    def _on_merge_error(self, exc: BaseException) -> None:
        self._status_lbl.setText(f"Merge-Fehler: {exc}")
        self._sync_btn.setEnabled(True)
        self._scan_btn.setEnabled(True)
        self._merge_btn.setEnabled(bool(self._dup_candidates))
        logger.exception("CRM merge failed: %s", exc)
        QMessageBox.warning(self, "CRM Merge", str(exc))

