"""Smoke-test: MainWindow can be constructed (pytest-qt)."""
from __future__ import annotations

from threading import Event

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget

from xw_office.bootstrap import register_default_services
from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.core.types import ModuleKey
from xw_office.core.worker import BackgroundWorker
from xw_office.ui.home_view import DASHBOARD_CARDS
from xw_office.ui.main_window import MainWindow
from xw_office.ui.sidebar import SIDEBAR_ENTRIES


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(MainWindow, "_start_startup_preload", lambda _self: None)
    monkeypatch.setattr(MainWindow, "_refresh_printer_status_async", lambda _self: None)
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    window = MainWindow(container)
    qtbot.addWidget(window)
    yield window
    window.close()
    qtbot.waitUntil(lambda: window._shutdown_finished, timeout=2000)  # noqa: SLF001


def test_main_window_opens(window: MainWindow) -> None:
    window.show()
    assert "XeisWorks" in window.windowTitle() or "Office" in window.windowTitle()

    window._page_factories[ModuleKey.RECHNUNGEN.value] = QWidget  # noqa: SLF001
    window._navigate_to(ModuleKey.RECHNUNGEN.value)  # noqa: SLF001
    assert window.page(ModuleKey.RECHNUNGEN) is None
    label = window._stack.currentWidget().findChild(QLabel)  # noqa: SLF001
    assert label is not None
    assert "wird geladen" in label.text()


def test_travel_costs_is_not_offered_in_navigation(window: MainWindow) -> None:
    assert all(entry.key is not ModuleKey.TRAVEL_COSTS for entry in SIDEBAR_ENTRIES)
    assert all(card["key"] is not ModuleKey.TRAVEL_COSTS for card in DASHBOARD_CARDS)
    assert ModuleKey.TRAVEL_COSTS.value not in window._page_factories  # noqa: SLF001


def test_close_hides_window_and_exits_after_workers_stop(window: MainWindow, qapp) -> None:
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
    assert window._printer_status_timer.isActive()  # noqa: SLF001
    window.close()

    assert not window.isVisible()
    assert not window._printer_status_timer.isActive()  # noqa: SLF001
    assert worker.cancelled
    assert not window._shutdown_finished  # noqa: SLF001

    QTimer.singleShot(100, release.set)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(lambda: qapp.exit(42))
    watchdog.start(2000)
    try:
        assert qapp.exec() == 0
    finally:
        release.set()
        watchdog.stop()
    assert window._shutdown_finished  # noqa: SLF001
    assert not worker.isRunning()
