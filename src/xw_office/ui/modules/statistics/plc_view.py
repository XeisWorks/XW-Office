"""Embedded PLC shipment statistics for the central statistics module."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.plc.statistics import PlcPeriodStatistics, PlcStatisticsService


class _PeriodPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self._summary = QLabel("—")
        self._summary.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self._summary)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Land", "Sendungen", "Gewicht", "Preis"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, stretch=1)

    def apply(self, stats: PlcPeriodStatistics) -> None:
        self._summary.setText(
            f"{stats.shipment_count} Sendungen · {stats.weight_kg:.2f} kg · "
            f"{stats.price_eur:.2f} € · {stats.date_range}"
        )
        self._table.setRowCount(len(stats.countries))
        for row_index, country in enumerate(stats.countries):
            values = (
                f"{country.country_name} ({country.country_iso2})",
                str(country.shipment_count),
                f"{country.weight_kg:.2f} kg",
                f"{country.price_eur:.2f} €" if country.priced_count else "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row_index, column, item)


class PlcStatisticsView(QWidget):
    def __init__(self, service: PlcStatisticsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._worker: BackgroundWorker | None = None
        self._pages: dict[str, _PeriodPage] = {}
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self._status = QLabel("PLC-Statistik wird geladen …")
        top.addWidget(self._status)
        top.addStretch()
        refresh = QPushButton("Aktualisieren")
        refresh.clicked.connect(self._load)
        self._refresh = refresh
        top.addWidget(refresh)
        layout.addLayout(top)
        self._tabs = QTabWidget()
        for key, title in (("week", "Woche"), ("month", "Monat"), ("year", "Jahr"), ("all", "Gesamt")):
            page = _PeriodPage()
            self._pages[key] = page
            self._tabs.addTab(page, title)
        layout.addWidget(self._tabs, stretch=1)
        self._load()

    def _load(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._refresh.setEnabled(False)
        self._worker = BackgroundWorker(self._service.load)
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(lambda exc: self._status.setText(f"Nicht verfügbar: {exc}"))
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()

    def _on_loaded(self, result: object) -> None:
        if isinstance(result, tuple):
            for stats in result:
                if isinstance(stats, PlcPeriodStatistics) and stats.key in self._pages:
                    self._pages[stats.key].apply(stats)
            self._status.setText("Quelle: PLC-Archiv und lokale LIVE-Sendungen")

    def _on_finished(self) -> None:
        self._worker = None
        self._refresh.setEnabled(True)

    def request_shutdown(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()

    def shutdown_complete(self) -> bool:
        return self._worker is None or not self._worker.isRunning()
