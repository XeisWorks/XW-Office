"""Cancellation behavior for background workers."""
from __future__ import annotations

import weakref
from threading import Event

from xw_office.core.worker import BackgroundWorker


def test_cancelled_worker_suppresses_result(qtbot: object) -> None:
    entered = Event()
    release = Event()
    results: list[object] = []

    def job() -> str:
        entered.set()
        release.wait(timeout=2)
        return "stale"

    worker = BackgroundWorker(job)
    worker.signals.result.connect(results.append)
    worker.start()
    assert entered.wait(timeout=1)
    worker.cancel()
    release.set()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=2000)

    assert worker.cancelled is True
    assert results == []


def test_worker_finished_signal_emits_after_qthread_stops(qtbot: object) -> None:
    running_states: list[bool] = []

    worker = BackgroundWorker(lambda: "done")
    worker.signals.finished.connect(lambda: running_states.append(worker.isRunning()))
    worker.start()

    qtbot.waitUntil(lambda: bool(running_states), timeout=2000)

    assert running_states == [False]


def test_running_worker_is_retained_without_an_owner_reference(qtbot: object) -> None:
    started = Event()
    release = Event()

    def job() -> None:
        started.set()
        release.wait(timeout=2)

    worker = BackgroundWorker(job)
    worker_ref = weakref.ref(worker)
    worker.start()
    assert started.wait(timeout=1)
    del worker

    assert worker_ref() is not None
    release.set()
    qtbot.waitUntil(lambda: worker_ref() is None, timeout=2000)
