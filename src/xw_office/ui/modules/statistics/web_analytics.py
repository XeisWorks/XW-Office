"""Compact view for aggregate analytics delivered by wix-sevdesk-api."""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.flow_api import FlowAnalyticsClient

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)


class WebAnalyticsView(QWidget):
    """Show aggregate webshop, payment and delivery KPIs."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._cards: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        self._status = QLabel("Noch nicht geladen")
        toolbar.addWidget(self._status)
        toolbar.addStretch()
        self._period = QComboBox()
        self._period.addItem("90 Tage", {"type": "days", "days": 90})
        self._period.addItem("30 Tage", {"type": "days", "days": 30})
        self._period.addItem("365 Tage", {"type": "days", "days": 365})
        self._period.addItem("Gesamt", {"type": "days", "days": 0})
        self._period.currentIndexChanged.connect(lambda _index: self._load())
        toolbar.addWidget(self._period)
        self._refresh = QPushButton("Aktualisieren")
        self._refresh.clicked.connect(self._load)
        toolbar.addWidget(self._refresh)
        root.addLayout(toolbar)

        cards = QGridLayout()
        cards.setSpacing(8)
        for index, (key, title) in enumerate(
            (
                ("orderCount", "Bestellungen"),
                ("deliveryCount", "Lieferungen"),
                ("revenue", "Umsatz"),
                ("averageOrderValue", "Ø Bestellwert"),
                ("medianPaymentHours", "Zahlungszeit Median"),
                ("averagePublishHours", "sevDesk-Laufzeit"),
            )
        ):
            box = QGroupBox(title)
            box_layout = QVBoxLayout(box)
            value = QLabel("—")
            value.setStyleSheet("font-size: 18px; font-weight: bold;")
            box_layout.addWidget(value)
            self._cards[key] = value
            cards.addWidget(box, index // 3, index % 3)
        root.addLayout(cards)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Bereich", "Wert", "Anteil"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table, stretch=1)
        self._load()

    def _load(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if not (self._container.config.flow_api.base_url or "").strip():
            self._status.setText("Nicht konfiguriert: XW_FLOW_API_BASE_URL")
            return
        client: FlowAnalyticsClient = self._container.resolve(FlowAnalyticsClient)
        period = dict(self._period.currentData() or {"type": "days", "days": 90})
        self._refresh.setEnabled(False)
        self._status.setText("Webshop-Analytics werden geladen …")
        self._worker = BackgroundWorker(lambda: client.load_summary(period))
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()

    def _on_loaded(self, payload: object) -> None:
        if not isinstance(payload, dict):
            self._on_error(RuntimeError("Ungültige Analytics-Antwort"))
            return
        analytics = payload.get("analytics")
        if not isinstance(analytics, dict):
            self._on_error(RuntimeError("Analytics-Antwort enthält keine Kennzahlen"))
            return
        for key, label in self._cards.items():
            self._cards[key].setText(self._format_value(key, analytics.get(key)))
        period = payload.get("period")
        label = period.get("label") if isinstance(period, dict) else ""
        generated = str(payload.get("generatedAt") or "")
        self._status.setText(f"Quelle: wix-sevdesk-api · {label} · {generated.replace('T', ' ')[:19]}")
        self._populate_table(analytics)

    def _populate_table(self, analytics: dict[str, Any]) -> None:
        rows: list[tuple[str, str, str]] = []
        for title, key in (("Zahlungsroute", "paymentRoutes"), ("Land", "countries"), ("Monat", "months")):
            values = analytics.get(key)
            if not isinstance(values, list):
                continue
            for item in values[:12]:
                if not isinstance(item, dict):
                    continue
                rows.append((f"{title}: {item.get('label', '—')}", str(item.get("count", 0)), f"{float(item.get('share', 0) or 0):.1f} %"))
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row_index, column, item)

    @staticmethod
    def _format_value(key: str, value: object) -> str:
        if value is None:
            return "—"
        if key in {"revenue", "averageOrderValue"}:
            return f"EUR {float(value):,.2f}"
        if key in {"medianPaymentHours", "averagePublishHours"}:
            return f"{float(value):.1f} h"
        return str(value)

    def _on_error(self, exc: BaseException) -> None:
        self._status.setText(f"Nicht verfügbar: {exc}")
        logger.warning("Web analytics load failed: %s", exc)

    def _on_finished(self) -> None:
        self._worker = None
        self._refresh.setEnabled(True)

    def request_shutdown(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()

    def shutdown_complete(self) -> bool:
        return self._worker is None or not self._worker.isRunning()
