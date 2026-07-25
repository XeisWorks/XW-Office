"""Compact week/month/year overview for successfully printed PLC labels."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.plc.statistics import PlcPeriodStatistics, PlcStatisticsService


class _StatisticsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        summary_row = QHBoxLayout()
        self._count = QLabel("Sendungen: —")
        self._count.setStyleSheet("font-size: 18px; font-weight: bold;")
        summary_row.addWidget(self._count)
        summary_row.addStretch()
        self._price = QLabel("Preis: —")
        self._price.setStyleSheet("font-size: 18px; font-weight: bold; color: #0f766e;")
        summary_row.addWidget(self._price)
        layout.addLayout(summary_row)

        self._range = QLabel("")
        self._range.setStyleSheet("color: #64748b;")
        layout.addWidget(self._range)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Land", "Sendungen", "Preis"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, stretch=1)

        self._empty = QLabel("Noch keine erfolgreich gedruckten LIVE-PLC-Labels in diesem Zeitraum.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #64748b; padding: 18px;")
        layout.addWidget(self._empty)

    def apply(self, stats: PlcPeriodStatistics) -> None:
        self._count.setText(f"Sendungen: {stats.shipment_count}")
        price = f"{stats.price_eur:.2f}".replace(".", ",")
        self._price.setText(f"Preis: {price} €")
        unknown = stats.shipment_count - stats.priced_count
        self._price.setToolTip(f"{unknown} Sendung(en) ohne hinterlegten Preis" if unknown else "")
        self._range.setText(stats.date_range)
        self._table.setRowCount(len(stats.countries))
        for row_index, country in enumerate(stats.countries):
            country_label = (
                f"{country.country_name} ({country.country_iso2})"
                if country.country_iso2 != "—"
                else country.country_name
            )
            country_price = (
                f"{country.price_eur:.2f} €".replace(".", ",")
                if country.priced_count
                else "—"
            )
            values = (country_label, str(country.shipment_count), country_price)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(row_index, column, item)
        has_rows = bool(stats.countries)
        self._table.setVisible(has_rows)
        self._empty.setVisible(not has_rows)


class PlcStatisticsDialog(QDialog):
    def __init__(self, service: PlcStatisticsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._worker: BackgroundWorker | None = None
        self._pages: dict[str, _StatisticsPage] = {}
        self.setWindowTitle("PLC-Übersicht")
        self.setMinimumSize(620, 440)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel("Erfolgreich gedruckte PLC-Labels")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        top.addWidget(title)
        top.addStretch()
        self._refresh = QPushButton("Aktualisieren")
        self._refresh.clicked.connect(self._reload)
        top.addWidget(self._refresh)
        layout.addLayout(top)

        self._status = QLabel("Lade Railway-Statistik …")
        self._status.setStyleSheet("color: #64748b;")
        layout.addWidget(self._status)

        self._tabs = QTabWidget()
        for key, label in (("week", "Woche"), ("month", "Monat"), ("year", "Jahr")):
            page = _StatisticsPage()
            self._pages[key] = page
            self._tabs.addTab(page, label)
        layout.addWidget(self._tabs, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reload(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._refresh.setEnabled(False)
        self._status.setText("Lade Railway-Statistik …")
        self._worker = BackgroundWorker(self._service.load)
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()

    def _on_loaded(self, result: object) -> None:
        if not isinstance(result, tuple):
            self._status.setText("Statistik konnte nicht gelesen werden.")
            return
        for stats in result:
            if isinstance(stats, PlcPeriodStatistics) and stats.key in self._pages:
                self._pages[stats.key].apply(stats)
        self._status.setText("LIVE-Sendungen · zentral aus Railway PostgreSQL")

    def _on_error(self, exc: Exception) -> None:
        self._status.setText(f"Statistik nicht verfügbar: {exc}")

    def _on_finished(self) -> None:
        self._worker = None
        self._refresh.setEnabled(True)
