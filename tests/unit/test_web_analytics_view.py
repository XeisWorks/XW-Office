"""Tests for defensive formatting of the aggregate web analytics view."""
from __future__ import annotations

from xw_office.ui.modules.statistics.web_analytics import WebAnalyticsView


def test_web_analytics_formats_numeric_values() -> None:
    assert WebAnalyticsView._format_value("revenue", 1250.5) == "EUR 1,250.50"
    assert WebAnalyticsView._format_value("averagePublishHours", 1.26) == "1.3 h"


def test_web_analytics_keeps_malformed_numeric_payload_visible() -> None:
    assert WebAnalyticsView._format_value("revenue", "unknown") == "unknown"
    assert WebAnalyticsView._format_value("averagePublishHours", {}) == "{}"
