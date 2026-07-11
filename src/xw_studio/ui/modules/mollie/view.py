"""Mollie auth queue view."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QWidget

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.daily_business.service import DailyBusinessService
from xw_studio.ui.widgets.data_table import DataTable
from xw_studio.ui.widgets.search_bar import SearchBar

if TYPE_CHECKING:
    from xw_studio.core.container import Container

_QUEUE_COLUMNS = ["Ref", "Kunde", "Betrag", "Status", "Hinweis", "Mark."]


class MollieView(QWidget):
    """Standalone Mollie queue, opened from Rechnungen toolbar alert button."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._rows: list[dict[str, str]] = []
        self._worker: BackgroundWorker | None = None
        self._last_loaded_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(60000)
        self._timer.timeout.connect(lambda: self.reload(force=True))
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Mollie Authorized")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

        row = QHBoxLayout()
        self._search = SearchBar("Suchen…")
        self._search.search_changed.connect(lambda text: self._table.set_filter(text, column=0))
        self._search.set_suggestion_provider(self._search_suggestions)
        row.addWidget(self._search, stretch=1)
        self._count_lbl = QLabel("0 Eintraege")
        row.addWidget(self._count_lbl)
        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(lambda: self.reload(force=True))
        row.addWidget(self._btn_refresh)
        layout.addLayout(row)

        self._table = DataTable(_QUEUE_COLUMNS)
        self._table.setSortingEnabled(False)
        self._table.horizontalHeader().setSectionsClickable(False)
        layout.addWidget(self._table, stretch=1)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.reload(force=False)
        self._timer.start()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        super().hideEvent(event)
        self._timer.stop()

    def reload(self, *, force: bool = True) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if not force and self._rows and (time.monotonic() - self._last_loaded_at) < 30.0:
            return
        self._btn_refresh.setEnabled(False)
        self._btn_refresh.setText("Aktualisiere...")
        if self._rows:
            self._count_lbl.setText(f"{len(self._rows)} Eintraege - aktualisiere...")

        def job() -> list[dict[str, str]]:
            service: DailyBusinessService = self._container.resolve(DailyBusinessService)
            return service.load_queue_rows("mollie", fallback_count=0)

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_result)
        self._worker.signals.error.connect(lambda _e: self._count_lbl.setText("Fehler"))
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()

    def _on_result(self, result: object) -> None:
        rows = [r for r in (result if isinstance(result, list) else []) if isinstance(r, dict)]
        self._rows = rows
        self._last_loaded_at = time.monotonic()
        self._table.set_data(rows)
        self._search.refresh_suggestions()
        self._count_lbl.setText(f"{len(rows)} Eintraege")

    def _on_finished(self) -> None:
        self._worker = None
        self._btn_refresh.setEnabled(True)
        self._btn_refresh.setText("Aktualisieren")

    def _search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 3:
            return []
        out: list[str] = []
        for row in self._rows:
            hay = f"{row.get('Ref', '')} {row.get('Kunde', '')} {row.get('Status', '')}".lower()
            if q in hay:
                out.append(f"{row.get('Ref', '—')} - {row.get('Kunde', '—')}")
        return out
