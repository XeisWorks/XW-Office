"""UI feedback and stale-result tests for :class:`UiAsyncAction`."""
from __future__ import annotations

from threading import Event

from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from xw_studio.ui.async_action import UiAsyncAction


def test_async_action_sets_and_restores_busy_state(qtbot: object) -> None:
    owner = QWidget()
    button = QPushButton("Laden", owner)
    status = QLabel(owner)
    qtbot.addWidget(owner)
    release = Event()
    results: list[object] = []
    action = UiAsyncAction(owner, button=button, status_label=status)

    assert action.start(
        lambda: release.wait(timeout=2) or "done",
        action_name="test-load",
        busy_text="Lade...",
        on_result=results.append,
    )
    assert not button.isEnabled()
    assert button.text() == "Lade..."
    assert status.text() == "Lade..."

    release.set()
    qtbot.waitUntil(lambda: not action.is_running(), timeout=2000)
    assert button.isEnabled()
    assert button.text() == "Laden"
    assert results == [True]


def test_async_action_cancel_suppresses_stale_result(qtbot: object) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    release = Event()
    results: list[object] = []
    action = UiAsyncAction(owner)

    action.start(
        lambda: release.wait(timeout=2) or "stale",
        action_name="stale-test",
        busy_text="Lade...",
        on_result=results.append,
    )
    action.cancel()
    release.set()
    qtbot.waitUntil(lambda: not action.is_running(), timeout=2000)
    assert results == []
