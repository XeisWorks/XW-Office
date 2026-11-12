from __future__ import annotations

import time

from xw_office.ui.performance import EventLoopWatchdog


def test_eventloop_gap_logs_active_print_job_context(caplog) -> None:
    watchdog = EventLoopWatchdog(context_provider=lambda: "id=job-123 kind=label backend=qt_raster active_ms=400")
    watchdog._last_tick = time.perf_counter() - 0.4  # noqa: SLF001
    caplog.set_level("WARNING", logger="xw_office.ui.performance")

    watchdog._tick()  # noqa: SLF001

    assert "active_print_job=id=job-123 kind=label backend=qt_raster active_ms=400" in caplog.text
    gaps = watchdog.snapshot()
    assert len(gaps) == 1
    assert gaps[0].context is not None
    assert "id=job-123" in gaps[0].context
