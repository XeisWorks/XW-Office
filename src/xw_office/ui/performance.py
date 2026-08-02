"""Runtime UI performance probes."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import time

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventLoopGap:
    elapsed_ms: int
    threshold_ms: int
    timestamp: float


class EventLoopWatchdog(QObject):
    """Log event-loop gaps that make the UI feel sluggish."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        interval_ms: int = 16,
        warn_ms: int = 50,
        critical_ms: int = 250,
        history_size: int = 100,
    ) -> None:
        super().__init__(parent)
        self._interval_ms = max(1, int(interval_ms))
        self._warn_ms = max(self._interval_ms, int(warn_ms))
        self._critical_ms = max(self._warn_ms, int(critical_ms))
        self._history_size = max(1, int(history_size))
        self._last_tick = time.perf_counter()
        self._gaps: list[EventLoopGap] = []
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._last_tick = time.perf_counter()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def snapshot(self) -> list[EventLoopGap]:
        return list(self._gaps)

    def _tick(self) -> None:
        now = time.perf_counter()
        elapsed_ms = int((now - self._last_tick) * 1000)
        self._last_tick = now
        if elapsed_ms < self._warn_ms:
            return
        threshold = self._critical_ms if elapsed_ms >= self._critical_ms else self._warn_ms
        gap = EventLoopGap(elapsed_ms=elapsed_ms, threshold_ms=threshold, timestamp=time.time())
        self._gaps.append(gap)
        if len(self._gaps) > self._history_size:
            del self._gaps[0 : len(self._gaps) - self._history_size]
        log = logger.warning if elapsed_ms >= self._critical_ms else logger.info
        log("Eventloop gap detected elapsed_ms=%s threshold_ms=%s", elapsed_ms, threshold)
