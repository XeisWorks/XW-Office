from __future__ import annotations

from xw_office.core.performance_metrics import PerformanceMetrics


def test_metrics_record_counters_and_recent_timing_samples() -> None:
    metrics = PerformanceMetrics(history_size=1)

    metrics.increment("wix.order_cache.hit")
    metrics.increment("wix.order_cache.hit", 2)
    metrics.record_elapsed("invoice_select_to_immediate_paint_ms", 0.0)
    metrics.record_elapsed("plc_click_to_dialog_setup_ms", 0.0)

    snapshot = metrics.snapshot()

    assert snapshot["counters"] == {"wix.order_cache.hit": 3}
    timings = snapshot["timings"]
    assert len(timings) == 1
    assert timings[0].name == "plc_click_to_dialog_setup_ms"
