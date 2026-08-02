"""Statistik module - live KPI cards and monthly revenue table."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.statistics import StatsSummary, StatisticsService
from xw_office.ui.widgets.data_table import DataTable

if TYPE_CHECKING:
    from xw_office.core.container import Container

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
    """Business analytics - KPI cards + monthly revenue table."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        bar = QHBoxLayout()
        self._status_lbl = QLabel("Statistiken werden geladen...")
        self._status_lbl.setObjectName("statsStatusLabel")
        bar.addWidget(self._status_lbl)
        bar.addStretch()
        self._refresh_btn = QPushButton("Aktualisieren")
        self._refresh_btn.clicked.connect(self._load)
        bar.addWidget(self._refresh_btn)
        root.addLayout(bar)

        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(10)
        self._card_total = _kpi_card("Rechnungen gesamt", "-")
        self._card_paid = _kpi_card("Bezahlt", "-")
        self._card_open = _kpi_card("Offen", "-")
        self._card_gross = _kpi_card("Gesamtumsatz (Brutto)", "-", accent=True)
        for card in (self._card_total, self._card_paid, self._card_open, self._card_gross):
            self._cards_row.addWidget(card)
        self._cards_row.addStretch()
        root.addLayout(self._cards_row)

        monthly_lbl = QLabel("Umsatz nach Monat")
        monthly_lbl.setObjectName("sectionLabel")
        root.addWidget(monthly_lbl)

        self._table = DataTable(["Monat", "Rechnungen", "Brutto EUR"])
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._table)

        self._load()

    def _load(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        svc: StatisticsService = self._container.resolve(StatisticsService)
        self._refresh_btn.setEnabled(False)
        self._status_lbl.setText("Laden...")

        def job() -> StatsSummary:
            return svc.load_summary()

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        self._worker = None

    def _on_loaded(self, summary: object) -> None:
        self._refresh_btn.setEnabled(True)
        if not isinstance(summary, StatsSummary):
            return
        src_tag = "sevDesk" if summary.source == "live" else "Mock"
        self._status_lbl.setText(
            f"Quelle: {src_tag} - {summary.total_invoices} Rechnungen analysiert"
        )
        self._update_cards(summary)
        self._populate_table(summary)

    def _on_error(self, exc: BaseException) -> None:
        self._refresh_btn.setEnabled(True)
        self._status_lbl.setText(f"Fehler: {exc}")
        logger.exception("StatisticsView load failed: %s", exc)

    def _update_cards(self, s: StatsSummary) -> None:
        def _val(card: QFrame) -> QLabel:
            return cast(
                "QLabel",
                card.findChild(QLabel, "kpiCardValue")
                or card.findChild(QLabel, "kpiCardValueAccent"),
            )

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
            lbl_gross.setText(f"EUR {s.total_gross:,.2f}")

    def _populate_table(self, s: StatsSummary) -> None:
        self._table.set_data(
            [
                {
                    "Monat": row.year_month,
                    "Rechnungen": str(row.invoice_count),
                    "Brutto EUR": f"EUR {row.gross_total:,.2f}",
                    "__sort__Rechnungen": row.invoice_count,
                    "__sort__Brutto EUR": row.gross_total,
                    "__align__Rechnungen": "center",
                    "__align__Brutto EUR": "right",
                }
                for row in reversed(s.by_month)
            ]
        )
