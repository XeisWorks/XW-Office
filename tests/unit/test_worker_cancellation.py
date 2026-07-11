"""Cancellation behavior for background workers."""
from __future__ import annotations

from threading import Event

from xw_studio.core.worker import BackgroundWorker


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
