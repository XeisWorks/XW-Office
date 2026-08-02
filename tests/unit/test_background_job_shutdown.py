from __future__ import annotations

from threading import Event

from xw_office.core.worker import BackgroundWorker
from xw_office.services.background_jobs import BackgroundJobManager


def test_shutdown_keeps_running_worker_alive_after_timeout(qtbot: object) -> None:
    started = Event()
    release = Event()

    def start_worker() -> BackgroundWorker:
        def job() -> None:
            started.set()
            release.wait(2)

        return BackgroundWorker(job)

    manager = BackgroundJobManager()
    handle = manager.submit(
        queue="network-background",
        priority=1,
        coalesce_key="shutdown-test",
        start_fn=start_worker,
    )
    assert started.wait(1)
    assert handle.worker is not None

    assert manager.shutdown(0) is False
    assert handle.worker.isRunning()

    release.set()
    assert manager.shutdown(1000) is True
    assert handle.worker.isRunning() is False


def test_shutdown_rejects_new_background_jobs() -> None:
    manager = BackgroundJobManager()

    assert manager.shutdown(0) is True

    handle = manager.submit_callable(
        queue="network-background",
        priority=1,
        key="late-job",
        fn=lambda token: "late",
    )

    assert handle.worker is None
    assert handle.token.cancelled
