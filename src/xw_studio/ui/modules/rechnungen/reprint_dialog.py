"""Reprint preview dialog — shows what will be printed vs what's in stock."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from xw_studio.ui.widgets.data_table import DataTable

logger = logging.getLogger(__name__)


class ReprintPreviewDialog(QDialog):
    """Review and confirm reprint operations before execution.

    Shows:
    - "ZU DRUCKEN" table: SKU, aktuelle Menge, Druck-Menge, neue Menge
    - "IM BESTAND" table: SKUs die nicht gedruckt werden (Stock OK)
    """

    def __init__(self, preflight: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preflight = preflight
        self.setWindowTitle("📋 Nachdrucke Übersicht")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # --- Header ---
        header = QLabel("Nachdrucke: Lagerfüllung (nur Auffüllung, kein Invoice-Konsum)")
        header.setStyleSheet("font-size: 13px; font-weight: bold; color: #1976d2;")
        layout.addWidget(header)

        # --- "ZU DRUCKEN" section ---
        gb_print = QGroupBox("🖨 ZU DRUCKEN")
        gb_print_layout = QVBoxLayout(gb_print)

        table_print = DataTable(["SKU", "Bestand jetzt", "Drucken", "Bestand nachher"])
        table_print.setSelectionMode(DataTable.SelectionMode.NoSelection)
        table_print.setMaximumHeight(200)

        to_print = [d for d in self.preflight.decisions if d.will_print]
        table_print.set_data(
            [
                {
                    "SKU": decision.sku,
                    "Bestand jetzt": str(decision.on_hand_qty),
                    "Drucken": str(decision.final_print_qty),
                    "Bestand nachher": str(decision.on_hand_qty + decision.final_print_qty),
                    "__bg__SKU": "#fff59d",
                    "__bg__Bestand jetzt": "#fff59d",
                    "__bg__Drucken": "#fff59d",
                    "__bg__Bestand nachher": "#fff59d",
                    "__fg__SKU": "#111111",
                    "__fg__Bestand jetzt": "#111111",
                    "__fg__Drucken": "#111111",
                    "__fg__Bestand nachher": "#111111",
                }
                for decision in to_print
            ]
        )

        gb_print_layout.addWidget(table_print)

        summary_print = QLabel(
            f"Gesamt: {len(to_print)} Positionen werden gedruckt "
            f"({sum(d.final_print_qty for d in to_print)} Stück)"
        )
        summary_print.setStyleSheet("font-size: 11px; color: #f57c00;")
        gb_print_layout.addWidget(summary_print)
        layout.addWidget(gb_print)

        # --- "IM BESTAND" section ---
        gb_stock = QGroupBox("✓ IM BESTAND (nicht nötig)")
        gb_stock_layout = QVBoxLayout(gb_stock)

        table_stock = DataTable(["SKU", "Bestand"])
        table_stock.setSelectionMode(DataTable.SelectionMode.NoSelection)
        table_stock.setMaximumHeight(150)

        in_stock = [d for d in self.preflight.decisions if not d.will_print]
        table_stock.set_data(
            [
                {
                    "SKU": decision.sku,
                    "Bestand": str(decision.on_hand_qty),
                    "__bg__SKU": "#16a34a",
                    "__bg__Bestand": "#16a34a",
                    "__fg__SKU": "#ffffff",
                    "__fg__Bestand": "#ffffff",
                }
                for decision in in_stock
            ]
        )

        gb_stock_layout.addWidget(table_stock)

        summary_stock = QLabel(f"Gesamt: {len(in_stock)} Positionen im ausreichenden Bestand")
        summary_stock.setStyleSheet("font-size: 11px; color: #2e7d32;")
        gb_stock_layout.addWidget(summary_stock)
        layout.addWidget(gb_stock)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
