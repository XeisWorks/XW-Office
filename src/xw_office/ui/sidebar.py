"""Collapsible sidebar with icon navigation, badges, and theme toggle."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.types import ModuleKey

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)


@dataclass
class SidebarEntry:
    key: ModuleKey
    label: str
    icon_name: str
    section: str


SIDEBAR_ENTRIES: list[SidebarEntry] = [
    SidebarEntry(ModuleKey.HOME, "Start", "home", ""),
    SidebarEntry(ModuleKey.RECHNUNGEN, "Rechnungen", "rechnungen", "Geschaeft"),
    SidebarEntry(ModuleKey.GUTSCHEINE, "Gutscheine", "gutscheine", "Geschaeft"),
    SidebarEntry(ModuleKey.PRODUCTS, "Produkte", "products", "Geschaeft"),
    SidebarEntry(ModuleKey.CRM, "CRM", "crm", "Geschaeft"),
    SidebarEntry(ModuleKey.TAXES, "Steuern", "taxes", "Finanzen"),
    SidebarEntry(ModuleKey.CLEARING, "Zahlungsclearing", "payment", "Finanzen"),
    SidebarEntry(ModuleKey.STATISTICS, "Statistik", "statistics", "Finanzen"),
    SidebarEntry(ModuleKey.CALCULATION, "Provisionen", "calculation", "Finanzen"),
    SidebarEntry(ModuleKey.LAYOUT, "Layout", "layout", "Medien"),
    SidebarEntry(ModuleKey.WUEDARAMUSI, "WuedaraMusi", "wuedaramusi", "Medien"),
    SidebarEntry(ModuleKey.MARKETING, "Marketing", "marketing", "Tools"),
    SidebarEntry(ModuleKey.NOTATION, "Notensatz", "notation", "Tools"),
    SidebarEntry(ModuleKey.XW_COPILOT, "XW-Copilot", "xw_copilot", "Tools"),
]


class SidebarButton(QPushButton):
    """Single navigation button in the sidebar."""

    def __init__(self, entry: SidebarEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setText(entry.label)
        self.setCheckable(True)
        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_theme(is_light=False)
        self._badge_count = 0

    def _apply_theme(self, *, is_light: bool) -> None:
        text_color = "#1f2937" if is_light else "#e8e8e8"
        checked_color = "#0f172a" if is_light else "#ffffff"
        accent = "#9c7a2e" if is_light else "#c9a24d"
        checked_bg = "rgba(156, 122, 46, 0.14)" if is_light else "rgba(201, 162, 77, 0.15)"
        hover_bg = "rgba(156, 122, 46, 0.08)" if is_light else "rgba(201, 162, 77, 0.10)"
        self.setStyleSheet(
            "QPushButton {"
            "text-align: left;"
            "padding: 8px 16px;"
            "border: none;"
            "border-left: 3px solid transparent;"
            "font-size: 14px;"
            f"color: {text_color};"
            "}"
            "QPushButton:checked {"
            f"border-left: 3px solid {accent};"
            "font-weight: bold;"
            f"color: {checked_color};"
            f"background-color: {checked_bg};"
            "}"
            "QPushButton:hover {"
            f"background-color: {hover_bg};"
            f"color: {checked_color};"
            "}"
        )

    def apply_theme_name(self, theme_name: str) -> None:
        self._apply_theme(is_light="light" in str(theme_name or "").lower())

    def set_badge(self, count: int) -> None:
        self._badge_count = count
        suffix = f"  ({count})" if count > 0 else ""
        self.setText(f"{self.entry.label}{suffix}")


class Sidebar(QFrame):
    """Collapsible navigation sidebar."""

    module_selected = Signal(str)

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._buttons: dict[str, SidebarButton] = {}
        self._collapsed = container.config.app.sidebar.default_collapsed
        self._current_theme: str = container.config.app.theme
        self._build_ui()
        from xw_office.core.signals import AppSignals

        app_signals = self._container.resolve(AppSignals)
        app_signals.navigate_to_module.connect(self._sync_sidebar_checkstate)
        app_signals.badge_updated.connect(self._on_badge_updated)
        self._select_module(ModuleKey.HOME.value)

    def _build_ui(self) -> None:
        self.setFixedWidth(self._current_width())
        self.setFrameShape(QFrame.Shape.NoFrame)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(12, 12, 12, 8)
        self._title_label = QLabel("XW Office")
        self._title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(self._title_label)
        header.addStretch()

        self._toggle_btn = QPushButton("â˜°")
        self._toggle_btn.setFixedSize(32, 32)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        header.addWidget(self._toggle_btn)
        main_layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        nav_widget = QWidget()
        self._nav_layout = QVBoxLayout(nav_widget)
        self._nav_layout.setContentsMargins(0, 0, 0, 0)
        self._nav_layout.setSpacing(2)

        current_section = ""
        for entry in SIDEBAR_ENTRIES:
            if entry.section and entry.section != current_section:
                current_section = entry.section
                sep = QLabel(f"  {current_section.upper()}")
                sep.setStyleSheet("font-size: 10px; color: #888; padding: 12px 0 4px 0;")
                self._nav_layout.addWidget(sep)

            btn = SidebarButton(entry)
            btn.apply_theme_name(self._current_theme)
            btn.clicked.connect(lambda checked, k=entry.key.value: self._select_module(k))
            self._buttons[entry.key.value] = btn
            self._nav_layout.addWidget(btn)

        self._nav_layout.addStretch()
        scroll.setWidget(nav_widget)
        main_layout.addWidget(scroll, stretch=1)

        footer = QHBoxLayout()
        footer.setContentsMargins(12, 8, 12, 12)

        settings_btn = QPushButton("Einstellungen")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(
            lambda: self._select_module(ModuleKey.SETTINGS.value)
        )
        footer.addWidget(settings_btn)
        footer.addStretch()

        self._theme_btn = QPushButton("â—")
        self._theme_btn.setFixedSize(32, 32)
        self._theme_btn.setToolTip("Theme wechseln")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        footer.addWidget(self._theme_btn)
        main_layout.addLayout(footer)

    def _current_width(self) -> int:
        cfg = self._container.config.app.sidebar
        return cfg.width_collapsed if self._collapsed else cfg.width_expanded

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self.setFixedWidth(self._current_width())
        self._title_label.setVisible(not self._collapsed)
        for btn in self._buttons.values():
            btn.setText("" if self._collapsed else btn.entry.label)

    def _sync_sidebar_checkstate(self, key: str) -> None:
        """Highlight sidebar entry when navigation comes from dashboard cards."""
        if key not in self._buttons:
            return
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)

    def _select_module(self, key: str) -> None:
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)
        self.module_selected.emit(key)

    def _on_badge_updated(self, module_key: str, count: int) -> None:
        btn = self._buttons.get(module_key)
        if btn is None:
            return
        btn.set_badge(max(0, int(count)))

    def _toggle_theme(self) -> None:
        """Cycle between dark and light variant of the current material palette."""
        if "dark" in self._current_theme:
            self._current_theme = self._current_theme.replace("dark", "light")
        else:
            self._current_theme = self._current_theme.replace("light", "dark")
        from xw_office.core.signals import AppSignals

        self._container.resolve(AppSignals).theme_changed.emit(self._current_theme)
        for btn in self._buttons.values():
            btn.apply_theme_name(self._current_theme)
        icon = "○" if "light" in self._current_theme else "◉"
        self._theme_btn.setText(icon)
