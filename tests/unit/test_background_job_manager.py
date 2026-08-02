from __future__ import annotations

from threading import Event

from xw_office.services.background_jobs.service import BackgroundJobManager


def test_manager_respects_queue_limit(qtbot) -> None:  # type: ignore[no-untyped-def]
    manager = BackgroundJobManager({"network-background": 1})
    release_first = Event()
    started: list[str] = []
    finished: list[str] = []

    def first_job(token) -> str:  # type: ignore[no-untyped-def]
        started.append("first")
        release_first.wait(timeout=2)
        token.raise_if_cancelled()
        return "first"

    first = manager.submit_callable(
        queue="network-background",
        priority=10,
        key="first",
        fn=first_job,
        on_result=lambda _payload: finished.append("first"),
        replace="allow_parallel",
    )
    second = manager.submit_callable(
        queue="network-background",
        priority=10,
        key="second",
        fn=lambda token: _mark_started(started, "second"),
        on_result=lambda _payload: finished.append("second"),
        replace="allow_parallel",
    )

    qtbot.waitUntil(lambda: started == ["first"], timeout=2000)
    assert second.worker is None
    release_first.set()

    qtbot.waitUntil(lambda: finished == ["first", "second"], timeout=2000)
    assert first.finished_at > 0
    assert second.finished_at > 0


def test_cancel_previous_suppresses_stale_result(qtbot) -> None:  # type: ignore[no-untyped-def]
    manager = BackgroundJobManager({"ui-critical-network": 1})
    release = Event()
    results: list[str] = []

    def slow_job(token) -> str:  # type: ignore[no-untyped-def]
        release.wait(timeout=2)
        token.raise_if_cancelled()
        return "old"

    old = manager.submit_callable(
        queue="ui-critical-network",
        priority=10,
        key="detail",
        fn=slow_job,
        on_result=lambda payload: results.append(str(payload)),
        replace="cancel_previous",
    )
    manager.submit_callable(
        queue="ui-critical-network",
        priority=10,
        key="detail",
        fn=lambda token: "new",
        on_result=lambda payload: results.append(str(payload)),
        replace="cancel_previous",
    )

    release.set()

    qtbot.waitUntil(lambda: results == ["new"], timeout=2000)
    assert old.token.cancelled


def _mark_started(started: list[str], value: str) -> str:
    started.append(value)
    return value
