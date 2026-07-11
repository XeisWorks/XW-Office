"""Statistik module — live KPI cards and monthly revenue table."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.statistics import StatsSummary, StatisticsService

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


def _kpi_card(title: str, value: str, *, accent: bool = False) -> QFrame:
    """Build a compact KPI card widget."""
    card = QFrame()
    card.setObjectName("kpiCard")
    card.setFrameShape(QFrame.Shape.StyledPanel)
    card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    vl = QVBoxLayout(card)
    vl.setContentsMargins(12, 8, 12, 8)
    vl.setSpacing(2)
    title_lbl = QLabel(title)
    title_lbl.setObjectName("kpiCardTitle")
    val_lbl = QLabel(value)
    val_lbl.setObjectName("kpiCardValueAccent" if accent else "kpiCardValue")
    vl.addWidget(title_lbl)
    vl.addWidget(val_lbl)
    return card


class StatisticsView(QWidget):
    """Business analytics — KPI cards + monthly revenue table."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # --- header ---
        bar = QHBoxLayout()
        self._status_lbl = QLabel("Statistiken werden geladen…")
        self._status_lbl.setObjectName("statsStatusLabel")
        bar.addWidget(self._status_lbl)
        bar.addStretch()
        self._refresh_btn = QPushButton("Aktualisieren")
        self._refresh_btn.clicked.connect(self._load)
        bar.addWidget(self._refresh_btn)
        root.addLayout(bar)

        # --- KPI cards row ---
        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(10)
        self._card_total = _kpi_card("Rechnungen gesamt", "—")
        self._card_paid = _kpi_card("Bezahlt", "—")
        self._card_open = _kpi_card("Offen", "—")
        self._card_gross = _kpi_card("Gesamtumsatz (Brutto)", "—", accent=True)
        for card in (self._card_total, self._card_paid, self._card_open, self._card_gross):
            self._cards_row.addWidget(card)
        self._cards_row.addStretch()
        root.addLayout(self._cards_row)

        # --- monthly table ---
        monthly_lbl = QLabel("Umsatz nach Monat")
        monthly_lbl.setObjectName("sectionLabel")
        root.addWidget(monthly_lbl)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Monat", "Rechnungen", "Brutto EUR"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._table)

        self._load()

    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        svc: StatisticsService = self._container.resolve(StatisticsService)
        self._refresh_btn.setEnabled(False)
        self._status_lbl.setText("Laden…")

        def job() -> StatsSummary:
            return svc.load_summary()

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._worker.start()

    def _on_loaded(self, summary: object) -> None:
        self._refresh_btn.setEnabled(True)
        if not isinstance(summary, StatsSummary):
            return
        src_tag = "sevDesk" if summary.source == "live" else "Mock"
        self._status_lbl.setText(
            f"Quelle: {src_tag} — {summary.total_invoices} Rechnungen analysiert"
        )
        self._update_cards(summary)
        self._populate_table(summary)

    def _on_error(self, exc: BaseException) -> None:
        self._refresh_btn.setEnabled(True)
        self._status_lbl.setText(f"Fehler: {exc}")
        logger.exception("StatisticsView load failed: %s", exc)

    def _update_cards(self, s: StatsSummary) -> None:
        def _val(card: QFrame) -> QLabel:
            return card.findChild(QLabel, "kpiCardValue") or card.findChild(QLabel, "kpiCardValueAccent")  # type: ignore[return-value]

        lbl_total = _val(self._card_total)
        if lbl_total:
            lbl_total.setText(str(s.total_invoices))
        lbl_paid = _val(self._card_paid)
        if lbl_paid:
            lbl_paid.setText(str(s.paid_invoices))
        lbl_open = _val(self._card_open)
        if lbl_open:
            lbl_open.setText(str(s.open_invoices))
        lbl_gross = _val(self._card_gross)
        if lbl_gross:
            lbl_gross.setText(f"€ {s.total_gross:,.2f}")

    def _populate_table(self, s: StatsSummary) -> None:
        tbl = self._table
        tbl.setRowCount(0)
        for row in reversed(s.by_month):
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(row.year_month))
            cnt_item = QTableWidgetItem(str(row.invoice_count))
            cnt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(r, 1, cnt_item)
            gross_item = QTableWidgetItem(f"€ {row.gross_total:,.2f}")
            gross_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tbl.setItem(r, 2, gross_item)
        tbl.resizeColumnToContents(1)
        tbl.resizeColumnToContents(2)

