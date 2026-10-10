"""Small, safe completion dialog for the dedicated open-print queue."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTextEdit, QVBoxLayout, QWidget

from xw_office.core.container import Container
from xw_office.core.worker import BackgroundWorker
from xw_office.services.drucke.service import OffeneDruckeService, PrintCase


class OffeneDruckeDialog(QDialog):
    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service: OffeneDruckeService = container.resolve(OffeneDruckeService)
        self._cases: list[PrintCase] = []
        self._worker: BackgroundWorker | None = None
        self.setWindowTitle("OPEN PRINTS")
        self.resize(800, 520)
        root = QVBoxLayout(self)
        top = QHBoxLayout(); self._status = QLabel("Lade Druckaufträge…")
        self._refresh = QPushButton("Aktualisieren"); self._refresh.clicked.connect(lambda: self._load(True))
        top.addWidget(self._status, 1); top.addWidget(self._refresh); root.addLayout(top)
        body = QHBoxLayout(); self._list = QListWidget(); self._list.currentRowChanged.connect(self._select)
        self._detail = QTextEdit(); self._detail.setReadOnly(True)
        body.addWidget(self._list, 1); body.addWidget(self._detail, 2); root.addLayout(body, 1)
        actions = QHBoxLayout(); self._done = QPushButton("Als erledigt markieren"); self._done.clicked.connect(self._mark_done)
        close = QPushButton("Schließen"); close.clicked.connect(self.accept)
        actions.addStretch(1); actions.addWidget(self._done); actions.addWidget(close); root.addLayout(actions)
        QTimer.singleShot(0, lambda: self._load(False))

    def _load(self, refresh: bool) -> None:
        if self._worker is not None and self._worker.isRunning(): return
        self._refresh.setEnabled(False)
        self._worker = BackgroundWorker(lambda: self._service.refresh_from_graph() if refresh else self._service.load_open_cases())
        self._worker.signals.result.connect(self._loaded); self._worker.signals.error.connect(lambda exc: self._status.setText(f"Fehler: {exc}"))
        self._worker.signals.finished.connect(lambda: self._refresh.setEnabled(True)); self._worker.start()

    def _loaded(self, result: object) -> None:
        self._cases = result if isinstance(result, list) else []
        self._list.clear()
        for case in self._cases:
            QListWidgetItem(f"{case.title}\n{case.received_at}", self._list)
        self._status.setText(f"{len(self._cases)} offene Druckaufträge")
        if self._cases: self._list.setCurrentRow(0)
        else: self._detail.clear()

    def _select(self, row: int) -> None:
        case = self._cases[row] if 0 <= row < len(self._cases) else None
        self._done.setEnabled(case is not None)
        self._detail.setPlainText("" if case is None else f"{case.title}\n\n{case.detail}\n\n{case.source_type}")

    def _mark_done(self) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._cases): return
        case = self._cases[row]
        self._service.mark_done(case.id, done=True)
        self._loaded([item for item in self._cases if item.id != case.id])

    def open_count(self) -> int:
        return len(self._cases)
