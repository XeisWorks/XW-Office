"""Dashboard home view with responsive card grid."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.types import ModuleKey

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)


DASHBOARD_CARDS = [
    {"key": ModuleKey.RECHNUNGEN, "title": "Rechnungen", "subtitle": "Rechnungen verarbeiten, drucken, versenden", "color": "#4fc3f7"},
    {"key": ModuleKey.PRODUCTS, "title": "Produkte", "subtitle": "Inventar, Wix-Sync, Druckplaene", "color": "#66bb6a"},
    {"key": ModuleKey.CRM, "title": "CRM", "subtitle": "Kunden verwalten, Duplikate bereinigen", "color": "#ffa726"},
    {"key": ModuleKey.TAXES, "title": "Steuern", "subtitle": "UVA und Ausgaben", "color": "#ef5350"},
    {"key": ModuleKey.CLEARING, "title": "Zahlungsclearing", "subtitle": "Stripe, Mollie, SEPA und sevDesk", "color": "#26a69a"},
    {"key": ModuleKey.STATISTICS, "title": "Statistik", "subtitle": "Umsatzanalysen, Charts, Export", "color": "#ab47bc"},
    {"key": ModuleKey.LAYOUT, "title": "Layout", "subtitle": "Covers, QR-Codes, Wasserzeichen, Leerseiten", "color": "#26c6da"},
    {"key": ModuleKey.CALCULATION, "title": "Provisionen", "subtitle": "Kalkulation, Druckrechte, Beteiligungen", "color": "#8d6e63"},
    {"key": ModuleKey.WUEDARAMUSI, "title": "WuedaraMusi", "subtitle": "WuedaraMusi Rechnungen", "color": "#d4e157"},
    {"key": ModuleKey.MARKETING, "title": "Marketing", "subtitle": "Content, Social Media, Newsletter", "color": "#ff7043"},
    {"key": ModuleKey.NOTATION, "title": "Notensatz", "subtitle": "Etueden, Transpositionen, Digitalisierung", "color": "#5c6bc0"},
]


class DashboardCard(QFrame):
    """Clickable card widget for the home dashboard."""

    def __init__(
        self, title: str, subtitle: str, accent_color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._accent = accent_color
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"""
            DashboardCard {{
                border: 1px solid #333;
                border-left: 4px solid {accent_color};
                border-radius: 8px;
                padding: 16px;
            }}
            DashboardCard:hover {{
                border-color: {accent_color};
                background-color: rgba(255, 255, 255, 0.03);
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {accent_color};")
        layout.addWidget(title_label)

        sub_label = QLabel(subtitle)
        sub_label.setStyleSheet("font-size: 12px; color: #aaa;")
        sub_label.setWordWrap(True)
        layout.addWidget(sub_label)
        layout.addStretch()


class HomeView(QWidget):
    """Dashboard home view with responsive card grid."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)

        header = QLabel("Willkommen bei XeisWorks Office")
        header.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 8px;")
        outer.addWidget(header)

        subtitle = QLabel("Waehle ein Modul, um zu starten.")
        subtitle.setStyleSheet("font-size: 14px; color: #999; margin-bottom: 24px;")
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        grid_widget = QWidget()
        self._grid = QGridLayout(grid_widget)
        self._grid.setSpacing(16)

        for i, card_def in enumerate(DASHBOARD_CARDS):
            card = DashboardCard(
                title=card_def["title"],
                subtitle=card_def["subtitle"],
                accent_color=card_def["color"],
            )
            key = card_def["key"]
            card.mousePressEvent = lambda event, k=key: self._on_card_click(k)
            row, col = divmod(i, 3)
            self._grid.addWidget(card, row, col)

        scroll.setWidget(grid_widget)
        outer.addWidget(scroll, stretch=1)

    def _on_card_click(self, key: ModuleKey) -> None:
        from xw_office.core.signals import AppSignals
        signals = self._container.resolve(AppSignals)
        signals.navigate_to_module.emit(key.value)
