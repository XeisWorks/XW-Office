"""Small, thread-safe runtime counters for performance regression diagnosis."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from threading import Lock
import time


@dataclass(frozen=True)
class TimingSample:
    name: str
    elapsed_ms: int
    timestamp: float


class PerformanceMetrics:
    """Keep inexpensive process-local counters and recent named timings."""

    def __init__(self, *, history_size: int = 200) -> None:
        self._lock = Lock()
        self._counters: Counter[str] = Counter()
        self._timings: deque[TimingSample] = deque(maxlen=max(1, history_size))

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[str(name)] += int(value)

    def record_elapsed(self, name: str, started_at: float) -> int:
        elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        with self._lock:
            self._timings.append(TimingSample(str(name), elapsed_ms, time.time()))
        return elapsed_ms

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"counters": dict(self._counters), "timings": list(self._timings)}


performance_metrics = PerformanceMetrics()
