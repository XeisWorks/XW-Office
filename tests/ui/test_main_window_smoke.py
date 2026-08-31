"""Smoke-test: MainWindow can be constructed (pytest-qt)."""
from __future__ import annotations

from threading import Event

from PySide6.QtWidgets import QLabel

from xw_office.bootstrap import register_default_services
from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.core.types import ModuleKey
from xw_office.core.worker import BackgroundWorker
from xw_office.ui.home_view import DASHBOARD_CARDS
from xw_office.ui.main_window import MainWindow
from xw_office.ui.sidebar import SIDEBAR_ENTRIES


def test_main_window_opens(qtbot: object) -> None:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.show()
    assert "XeisWorks" in window.windowTitle() or "Office" in window.windowTitle()

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


def test_close_hides_window_and_finishes_cancelled_worker_automatically(qtbot: object, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "_start_startup_preload", lambda _self: None)
    monkeypatch.setattr(MainWindow, "_refresh_printer_status_async", lambda _self: None)
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    window = MainWindow(container)
    qtbot.addWidget(window)

    started = Event()
    release = Event()

    def job() -> None:
        started.set()
        release.wait(2)

    worker = BackgroundWorker(job)
    window._startup_preload_worker = worker  # noqa: SLF001
    worker.start()
    assert started.wait(1)

    window.show()
    window.close()

    assert not window.isVisible()
    assert worker.cancelled
    assert not window._shutdown_finished  # noqa: SLF001

    release.set()
    qtbot.waitUntil(lambda: window._shutdown_finished, timeout=2000)  # noqa: SLF001
    assert not worker.isRunning()
