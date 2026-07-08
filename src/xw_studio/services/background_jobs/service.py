"""Small priority/coalescing background job manager."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
from typing import Callable

from PySide6.QtCore import QTimer

from xw_studio.core.worker import BackgroundWorker


@dataclass
class _QueuedJob:
    queue: str
    priority: int
    order: int
    coalesce_key: str
    start_fn: Callable[[], BackgroundWorker | None]
    can_start: Callable[[], bool] | None = None


class BackgroundJobManager:
    """Coordinate low-priority background work with simple queue priorities."""

    def __init__(self) -> None:
        self._counter = itertools.count()
        self._queues: dict[str, list[_QueuedJob]] = {}
        self._active: dict[str, BackgroundWorker] = {}

    def submit(
        self,
        *,
        queue: str,
        priority: int,
        coalesce_key: str,
        start_fn: Callable[[], BackgroundWorker | None],
        can_start: Callable[[], bool] | None = None,
    ) -> None:
        jobs = self._queues.setdefault(queue, [])
        jobs[:] = [job for job in jobs if job.coalesce_key != coalesce_key]
        jobs.append(
            _QueuedJob(
                queue=queue,
                priority=int(priority),
                order=next(self._counter),
                coalesce_key=str(coalesce_key),
                start_fn=start_fn,
                can_start=can_start,
            )
        )
        jobs.sort(key=lambda job: (job.priority, job.order))
        self._try_start(queue)

    def has_active_job(self, queue: str) -> bool:
        worker = self._active.get(queue)
        return bool(worker is not None and worker.isRunning())

    def _try_start(self, queue: str) -> None:
        active = self._active.get(queue)
        if active is not None and active.isRunning():
            return
        jobs = self._queues.get(queue, [])
        if not jobs:
            self._active.pop(queue, None)
            return

        for index, job in enumerate(list(jobs)):
            if job.can_start is not None and not job.can_start():
                continue
            worker = job.start_fn()
            del jobs[index]
            if worker is None:
                QTimer.singleShot(0, lambda q=queue: self._try_start(q))
                return
            self._active[queue] = worker
            worker.signals.finished.connect(lambda q=queue: self._on_worker_finished(q))
            worker.start()
            return

    def _on_worker_finished(self, queue: str) -> None:
        self._active.pop(queue, None)
        QTimer.singleShot(0, lambda q=queue: self._try_start(q))
