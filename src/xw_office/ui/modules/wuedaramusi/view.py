"""WuedaraMusi - legacy music publishing workflow and archive."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)

_INFO_NOTE = (
    "WuedaraMusi ist das Legacy-Modul fuer altprojekt-basierte Musik-Publishing-Workflows.\n\n"
    "Funktionen:\n"
    "  - Stueckverzeichnis: Kompositionen / Arrangements erfassen\n"
    "  - Verlag-Workflow: Einreichungs- und Genehmigungsstatus pro Stueck\n"
    "  - Archiv-Notizen: Freitextnotizen zum Altprojekt-Datenimport\n\n"
    "Status: Migration aus Altprojekt laufend."
)

_SAMPLE_PIECES = [
    "Etüde Nr. 1 - As-Dur",
    "Sonate für Klavier op. 3",
    "Variationen über ein Volkslied",
    "Streichquartett Nr. 2",
    "Liederzyklus - Herbstblätter",
]


class WuedaraMusiView(QWidget):
    """Legacy music publishing workflow and archive module."""

    def __init__(self, container: "Container", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        header = QLabel("WuedaraMusi - Musik-Publishing & Altprojekt-Archiv")
        header.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 8px;")
        root.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_stuecke_tab(), "Stücke")
        tabs.addTab(self._build_workflow_tab(), "Verlag-Workflow")
        tabs.addTab(self._build_archiv_tab(), "Archiv-Notizen")
        root.addWidget(tabs)

    def _build_stuecke_tab(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.addWidget(QLabel("Stücke:"))
        self._piece_list = QListWidget()
        for p in _SAMPLE_PIECES:
            self._piece_list.addItem(p)
        self._piece_list.currentTextChanged.connect(self._on_piece_selected)
        left_lay.addWidget(self._piece_list, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Hinzufügen")
        add_btn.clicked.connect(self._add_piece)
        btn_row.addWidget(add_btn)
        remove_btn = QPushButton("Entfernen")
        remove_btn.clicked.connect(self._remove_piece)
        btn_row.addWidget(remove_btn)
        left_lay.addLayout(btn_row)
        splitter.addWidget(left)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 0, 0, 0)
        detail_group = QGroupBox("Stück-Details")
        form = QFormLayout(detail_group)

        self._piece_title = QLineEdit()
        self._piece_title.setPlaceholderText("Vollständiger Titel")
        form.addRow("Titel:", self._piece_title)

        self._piece_opus = QLineEdit()
        self._piece_opus.setPlaceholderText("op. 3 / Nr. 2 ...")
        form.addRow("Opus / Nr.:", self._piece_opus)

        self._piece_key = QLineEdit()
        self._piece_key.setPlaceholderText("z. B. As-Dur, h-Moll")
        form.addRow("Tonart:", self._piece_key)

        self._piece_instrumentation = QLineEdit()
        self._piece_instrumentation.setPlaceholderText("Klavier, Streichquartett, ...")
        form.addRow("Besetzung:", self._piece_instrumentation)

        self._piece_notes = QPlainTextEdit()
        self._piece_notes.setPlaceholderText("Notizen, Entstehungsgeschichte, Aufführungen ...")
        self._piece_notes.setMaximumHeight(120)
        form.addRow("Notizen:", self._piece_notes)

        right_lay.addWidget(detail_group)
        right_lay.addStretch()
        splitter.addWidget(right)

        splitter.setSizes([240, 460])
        lay.addWidget(splitter)
        return page

    def _on_piece_selected(self, title: str) -> None:
        self._piece_title.setText(title)
        self._piece_opus.clear()
        self._piece_key.clear()
        self._piece_instrumentation.clear()
        self._piece_notes.clear()

    def _add_piece(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        title, ok = QInputDialog.getText(self, "Neues Stück", "Titel eingeben:")
        if ok and title.strip():
            self._piece_list.addItem(title.strip())

    def _remove_piece(self) -> None:
        row = self._piece_list.currentRow()
        if row >= 0:
            self._piece_list.takeItem(row)

    def _build_workflow_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Verlag-Einreichungsstatus pro Werk:"))

        workflow_group = QGroupBox("Aktueller Workflow-Status")
        wf_form = QFormLayout(workflow_group)

        self._wf_werk = QLineEdit()
        self._wf_werk.setPlaceholderText("Werkname oder Opus")
        wf_form.addRow("Werk:", self._wf_werk)

        self._wf_verlag = QLineEdit()
        self._wf_verlag.setPlaceholderText("Verlagsname")
        wf_form.addRow("Verlag:", self._wf_verlag)

        self._wf_status = QLineEdit()
        self._wf_status.setPlaceholderText("z. B. eingereicht, in Prüfung, genehmigt, abgelehnt")
        wf_form.addRow("Status:", self._wf_status)

        self._wf_datum = QLineEdit()
        self._wf_datum.setPlaceholderText("TT.MM.JJJJ")
        wf_form.addRow("Datum:", self._wf_datum)

        self._wf_notiz = QPlainTextEdit()
        self._wf_notiz.setPlaceholderText("Anmerkungen zur Einreichung ...")
        self._wf_notiz.setMaximumHeight(100)
        wf_form.addRow("Anmerkung:", self._wf_notiz)

        btn_row = QHBoxLayout()
        log_btn = QPushButton("Eintrag protokollieren")
        log_btn.clicked.connect(self._log_workflow_entry)
        btn_row.addWidget(log_btn)
        btn_row.addStretch()
        wf_form.addRow("", btn_row)

        lay.addWidget(workflow_group)
        lay.addWidget(QLabel("Protokoll:"))
        self._wf_log = QTextEdit()
        self._wf_log.setReadOnly(True)
        self._wf_log.setPlaceholderText("Keine Einträge.")
        lay.addWidget(self._wf_log, stretch=1)
        return page

    def _log_workflow_entry(self) -> None:
        werk = self._wf_werk.text().strip()
        verlag = self._wf_verlag.text().strip()
        status = self._wf_status.text().strip()
        datum = self._wf_datum.text().strip()
        notiz = self._wf_notiz.toPlainText().strip()
        if not werk:
            QMessageBox.warning(self, "WuedaraMusi", "Bitte Werkname angeben.")
            return
        line = f"[{datum or 'k.A.'}] {werk}"
        if verlag:
            line += f" @ {verlag}"
        if status:
            line += f" - {status}"
        if notiz:
            line += f"\n    {notiz}"
        self._wf_log.append(line)
        logger.info("WuedaraMusi workflow entry: %s", line.split("\n")[0])

    def _build_archiv_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        info = QLabel(_INFO_NOTE)
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addWidget(QLabel("Freitextnotizen zur Datenmigration:"))
        self._archiv_notes = QPlainTextEdit()
        self._archiv_notes.setPlaceholderText(
            "Hier Notizen zum Altprojekt eintragen: Dateinamen, Mapping-Hinweise, offene Punkte ..."
        )
        lay.addWidget(self._archiv_notes, stretch=1)

        save_btn = QPushButton("Notizen speichern (lokal)")
        save_btn.clicked.connect(self._save_archiv_notes)
        lay.addWidget(save_btn)
        self._archiv_status = QLabel("")
        lay.addWidget(self._archiv_status)
        return page

    def _save_archiv_notes(self) -> None:
        """Log archiv notes (DB persistence deferred to future migration ticket)."""
        text = self._archiv_notes.toPlainText().strip()
        if text:
            logger.info("WuedaraMusi archiv notes captured (in-memory): %d chars", len(text))
            self._archiv_status.setText(
                f"{len(text)} Zeichen erfasst (In-Memory, noch nicht in DB)."
            )
        else:
            self._archiv_status.setText("Keine Notizen.")
