from __future__ import annotations

import time

import pytest

from xw_office.ui.performance import EventLoopWatchdog


def test_eventloop_gap_logs_active_print_job_context(caplog: pytest.LogCaptureFixture) -> None:
    watchdog = EventLoopWatchdog(context_provider=lambda: "id=job-123 kind=label backend=qt_raster active_ms=400")
    watchdog._last_tick = time.perf_counter() - 0.4  # noqa: SLF001
    watchdog._last_process_cpu = time.process_time() - 0.3  # noqa: SLF001
    watchdog._last_ui_thread_cpu = time.thread_time() - 0.05  # noqa: SLF001
    caplog.set_level("WARNING", logger="xw_office.ui.performance")

    watchdog._tick()  # noqa: SLF001

    assert "active_print_job=id=job-123 kind=label backend=qt_raster active_ms=400" in caplog.text
    assert "process_cpu_ms=" in caplog.text
    assert "ui_thread_cpu_ms=" in caplog.text
    gaps = watchdog.snapshot()
    assert len(gaps) == 1
    assert gaps[0].context is not None
    assert "id=job-123" in gaps[0].context
    assert gaps[0].process_cpu_ms >= 250
    assert 0 < gaps[0].ui_thread_cpu_ms < gaps[0].process_cpu_ms
