"""OPEN PRINTS dialog with safe local opening of mail attachments."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget

from xw_office.core.container import Container
from xw_office.core.worker import BackgroundWorker
from xw_office.services.drucke.service import OffeneDruckeService, PrintAttachment, PrintCase


class OffeneDruckeDialog(QDialog):
    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service: OffeneDruckeService = container.resolve(OffeneDruckeService)
        self._cases: list[PrintCase] = []
        self._attachments: list[PrintAttachment] = []
        self._worker: BackgroundWorker | None = None
        self._attachment_worker: BackgroundWorker | None = None
        self.setWindowTitle("OPEN PRINTS"); self.resize(960, 600)
        root = QVBoxLayout(self)
        top = QHBoxLayout(); self._status = QLabel("Lade Druckaufträge…")
        self._refresh = QPushButton("Aktualisieren"); self._refresh.clicked.connect(lambda: self._load(True))
        top.addWidget(self._status, 1); top.addWidget(self._refresh); root.addLayout(top)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget(); self._list.currentRowChanged.connect(self._select); splitter.addWidget(self._list)
        right = QWidget(); right_layout = QVBoxLayout(right)
        self._detail = QTextEdit(); self._detail.setReadOnly(True); right_layout.addWidget(self._detail, 1)
        right_layout.addWidget(QLabel("Anhänge"))
        self._attachment_list = QListWidget(); self._attachment_list.itemDoubleClicked.connect(lambda _item: self._open_attachment()); self._attachment_list.setMaximumHeight(150); right_layout.addWidget(self._attachment_list)
        self._open_attachment_button = QPushButton("Anhang öffnen"); self._open_attachment_button.clicked.connect(self._open_attachment); self._open_attachment_button.setEnabled(False); right_layout.addWidget(self._open_attachment_button)
        splitter.addWidget(right); splitter.setStretchFactor(0, 1); splitter.setStretchFactor(1, 2); root.addWidget(splitter, 1)
        actions = QHBoxLayout(); self._done = QPushButton("Als erledigt markieren"); self._done.clicked.connect(self._mark_done); self._done.setEnabled(False)
        close = QPushButton("Schließen"); close.clicked.connect(self.accept); actions.addStretch(1); actions.addWidget(self._done); actions.addWidget(close); root.addLayout(actions)
        # The alert itself is a retry point for the Office -> Flow bridge.
        QTimer.singleShot(0, lambda: self._load(True))

    def _load(self, refresh: bool) -> None:
        if self._worker is not None and self._worker.isRunning(): return
        self._refresh.setEnabled(False); self._status.setText("Aktualisiere OPEN PRINTS…")
        self._worker = BackgroundWorker(lambda: self._service.refresh_from_graph() if refresh else self._service.load_open_cases())
        self._worker.signals.result.connect(self._loaded); self._worker.signals.error.connect(self._load_error); self._worker.signals.finished.connect(lambda: self._refresh.setEnabled(True)); self._worker.start()

    def _loaded(self, result: object) -> None:
        self._cases = result if isinstance(result, list) else []; self._list.clear()
        for case in self._cases:
            item = QListWidgetItem(f"{case.title}\n{case.received_at}"); item.setData(Qt.ItemDataRole.UserRole, case.id); self._list.addItem(item)
        diagnostic = self._service.last_flow_sync_error()
        self._status.setText(f"{len(self._cases)} offene Druckaufträge" + (f" · {diagnostic}" if diagnostic else ""))
        if self._cases: self._list.setCurrentRow(0)
        else: self._clear_detail()

    def _load_error(self, exc: Exception) -> None:
        self._status.setText("Aktualisieren fehlgeschlagen"); QMessageBox.warning(self, "OPEN PRINTS", f"Druckaufträge konnten nicht geladen werden:\n\n{exc}")

    def _clear_detail(self) -> None:
        self._detail.clear(); self._attachment_list.clear(); self._attachments = []; self._done.setEnabled(False); self._open_attachment_button.setEnabled(False)

    def _current_case(self) -> PrintCase | None:
        row = self._list.currentRow()
        return self._cases[row] if 0 <= row < len(self._cases) else None

    def _select(self, _row: int) -> None:
        case = self._current_case()
        if case is None: self._clear_detail(); return
        self._done.setEnabled(True); self._detail.setPlainText(f"{case.title}\n\n{case.detail}\n\nQuelle: {case.source_type}")
        self._attachment_list.clear(); self._attachments = []; self._open_attachment_button.setEnabled(False)
        if self._attachment_worker is not None and self._attachment_worker.isRunning(): return
        self._attachment_worker = BackgroundWorker(lambda: self._service.list_attachments(case.id))
        self._attachment_worker.signals.result.connect(self._attachments_loaded); self._attachment_worker.signals.error.connect(lambda exc: self._status.setText(f"Anhänge konnten nicht geladen werden: {exc}")); self._attachment_worker.start()

    def _attachments_loaded(self, result: object) -> None:
        self._attachments = result if isinstance(result, list) else []; self._attachment_list.clear()
        for attachment in self._attachments:
            item = QListWidgetItem(f"{attachment.name} ({self._format_size(attachment.size_bytes)})"); item.setData(Qt.ItemDataRole.UserRole, attachment.id); self._attachment_list.addItem(item)
        self._open_attachment_button.setEnabled(bool(self._attachments))
        if self._attachments: self._attachment_list.setCurrentRow(0)

    def _open_attachment(self) -> None:
        case = self._current_case(); row = self._attachment_list.currentRow()
        if case is None or not 0 <= row < len(self._attachments) or (self._attachment_worker is not None and self._attachment_worker.isRunning()): return
        attachment = self._attachments[row]; self._open_attachment_button.setEnabled(False)
        self._attachment_worker = BackgroundWorker(lambda: self._service.download_attachment_to_cache(case.id, attachment.id, attachment.name))
        self._attachment_worker.signals.result.connect(self._open_local_file); self._attachment_worker.signals.error.connect(lambda exc: QMessageBox.warning(self, "Anhang öffnen", str(exc))); self._attachment_worker.signals.finished.connect(lambda: self._open_attachment_button.setEnabled(True)); self._attachment_worker.start()

    def _open_local_file(self, value: object) -> None:
        path = value if isinstance(value, Path) else None
        if path is None or not path.is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))): QMessageBox.warning(self, "Anhang öffnen", "Die Datei konnte nicht mit dem Windows-Standardprogramm geöffnet werden.")

    def _mark_done(self) -> None:
        case = self._current_case()
        if case is None: return
        self._service.mark_done(case.id, done=True); self._loaded([item for item in self._cases if item.id != case.id])

    def open_count(self) -> int: return len(self._cases)

    @staticmethod
    def _format_size(size_bytes: int) -> str: return f"{size_bytes / 1024:.0f} KB" if size_bytes >= 1024 else f"{size_bytes} B"
