"""Smoke-test: MainWindow can be constructed (pytest-qt)."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from xw_studio.bootstrap import register_default_services
from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container
from xw_studio.core.signals import AppSignals
from xw_studio.core.types import ModuleKey
from xw_studio.ui.home_view import DASHBOARD_CARDS
from xw_studio.ui.main_window import MainWindow
from xw_studio.ui.sidebar import SIDEBAR_ENTRIES


def test_main_window_opens(qtbot: object) -> None:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.show()
    assert "XeisWorks" in window.windowTitle() or "Studio" in window.windowTitle()

    window._navigate_to(ModuleKey.RECHNUNGEN.value)  # noqa: SLF001
    assert window.page(ModuleKey.RECHNUNGEN) is None
    label = window._stack.currentWidget().findChild(QLabel)  # noqa: SLF001
    assert label is not None
    assert "wird geladen" in label.text()


def test_travel_costs_is_not_offered_in_navigation(qtbot: object) -> None:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    window = MainWindow(container)
    qtbot.addWidget(window)

    assert all(entry.key is not ModuleKey.TRAVEL_COSTS for entry in SIDEBAR_ENTRIES)
    assert all(card["key"] is not ModuleKey.TRAVEL_COSTS for card in DASHBOARD_CARDS)
    assert ModuleKey.TRAVEL_COSTS.value not in window._page_factories  # noqa: SLF001
