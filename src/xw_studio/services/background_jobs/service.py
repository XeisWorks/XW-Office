"""Priority/coalescing background job manager with queue limits."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import itertools
import logging
import time
from threading import Event
from typing import Any, Literal
import weakref

from PySide6.QtCore import QObject, QTimer

from xw_studio.core.worker import BackgroundWorker

logger = logging.getLogger(__name__)

ReplacePolicy = Literal["coalesce_pending", "cancel_previous", "allow_parallel"]

_DEFAULT_QUEUE_LIMITS: dict[str, int] = {
    "ui-critical-network": 3,
    "network-background": 2,
    "database": 3,
    "cpu": 3,
    "printing": 1,
    "export": 1,
    "default": 2,
}


class CancelToken:
    """Cooperative cancellation token passed into managed jobs."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled


class JobCancelled(Exception):
    """Internal signal for a cooperatively cancelled job."""


@dataclass
class JobHandle:
    """Lightweight handle returned by managed submissions."""

    key: str
    queue: str
    token: CancelToken
    worker: BackgroundWorker | None = None
    started_at: float = 0.0
    queued_at: float = field(default_factory=time.perf_counter)
    finished_at: float = 0.0

    @property
    def running(self) -> bool:
        return bool(self.worker is not None and self.worker.isRunning())

    def cancel(self) -> None:
        self.token.cancel()
        if self.worker is not None:
            self.worker.cancel()


@dataclass
class _QueuedJob:
    queue: str
    priority: int
    order: int
    coalesce_key: str
    start_fn: Callable[[], BackgroundWorker | None]
    can_start: Callable[[], bool] | None = None
    handle: JobHandle | None = None
    owner_ref: weakref.ReferenceType[QObject] | None = None


class BackgroundJobManager:
    """Coordinate UI background work with priority, limits and cancellation."""

    def __init__(self, queue_limits: dict[str, int] | None = None) -> None:
        self._counter = itertools.count()
        self._queues: dict[str, list[_QueuedJob]] = {}
        self._active: dict[str, list[BackgroundWorker]] = {}
        self._active_jobs: dict[str, list[_QueuedJob]] = {}
        self._queue_limits = dict(_DEFAULT_QUEUE_LIMITS)
        if queue_limits:
            self._queue_limits.update({str(key): max(1, int(value)) for key, value in queue_limits.items()})

    def submit(
        self,
        *,
        queue: str,
        priority: int,
        coalesce_key: str,
        start_fn: Callable[[], BackgroundWorker | None],
        can_start: Callable[[], bool] | None = None,
        owner: QObject | None = None,
        replace: ReplacePolicy = "coalesce_pending",
    ) -> JobHandle:
        """Submit a custom-worker job.

        This keeps the older API intact while adding queue limits and optional
        cancellation of pending/running jobs with the same key.
        """
        queue_name = str(queue or "default")
        key = str(coalesce_key)
        token = CancelToken()
        handle = JobHandle(key=key, queue=queue_name, token=token)
        owner_ref = weakref.ref(owner) if owner is not None else None
        if replace == "cancel_previous":
            self.cancel_key(key)
        elif replace == "coalesce_pending":
            self._drop_pending(queue_name, key)

        job = _QueuedJob(
            queue=queue_name,
            priority=int(priority),
            order=next(self._counter),
            coalesce_key=key,
            start_fn=start_fn,
            can_start=can_start,
            handle=handle,
            owner_ref=owner_ref,
        )
        self._queues.setdefault(queue_name, []).append(job)
        self._sort_queue(queue_name)
        self._try_start(queue_name)
        return handle

    def submit_callable(
        self,
        *,
        queue: str,
        priority: int,
        key: str,
        fn: Callable[[CancelToken], Any],
        on_result: Callable[[object], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        owner: QObject | None = None,
        replace: ReplacePolicy = "cancel_previous",
        can_start: Callable[[], bool] | None = None,
    ) -> JobHandle:
        """Submit a callable that receives a cooperative cancellation token."""
        token = CancelToken()
        handle = JobHandle(key=str(key), queue=str(queue or "default"), token=token)

        def start_fn() -> BackgroundWorker | None:
            def job() -> Any:
                token.raise_if_cancelled()
                return fn(token)

            worker = BackgroundWorker(job)
            handle.worker = worker
            if on_result is not None:
                worker.signals.result.connect(on_result)
            if on_error is not None:
                worker.signals.error.connect(on_error)
            if on_finished is not None:
                worker.signals.finished.connect(on_finished)
            return worker

        queue_name = handle.queue
        if replace == "cancel_previous":
            self.cancel_key(handle.key)
        elif replace == "coalesce_pending":
            self._drop_pending(queue_name, handle.key)

        owner_ref = weakref.ref(owner) if owner is not None else None
        job = _QueuedJob(
            queue=queue_name,
            priority=int(priority),
            order=next(self._counter),
            coalesce_key=handle.key,
            start_fn=start_fn,
            can_start=can_start,
            handle=handle,
            owner_ref=owner_ref,
        )
        self._queues.setdefault(queue_name, []).append(job)
        self._sort_queue(queue_name)
        self._try_start(queue_name)
        return handle

    def cancel_key(self, coalesce_key: str) -> None:
        key = str(coalesce_key)
        for queue in list(self._queues):
            self._drop_pending(queue, key, cancel=True)
        for jobs in list(self._active_jobs.values()):
            for job in list(jobs):
                if job.coalesce_key == key and job.handle is not None:
                    job.handle.cancel()

    def cancel_owner(self, owner: QObject) -> None:
        for queue in list(self._queues):
            jobs = self._queues.get(queue, [])
            kept: list[_QueuedJob] = []
            for job in jobs:
                if self._owner_alive(job.owner_ref, owner):
                    if job.handle is not None:
                        job.handle.cancel()
                    continue
                kept.append(job)
            self._queues[queue] = kept
        for jobs in list(self._active_jobs.values()):
            for job in list(jobs):
                if self._owner_alive(job.owner_ref, owner) and job.handle is not None:
                    job.handle.cancel()

    def has_active_job(self, queue: str) -> bool:
        return any(worker.isRunning() for worker in self._active.get(queue, []))

    def active_count(self, queue: str) -> int:
        return sum(1 for worker in self._active.get(queue, []) if worker.isRunning())

    def set_queue_limit(self, queue: str, limit: int) -> None:
        self._queue_limits[str(queue)] = max(1, int(limit))
        self._try_start(str(queue))

    def shutdown(self, wait_ms: int = 30000) -> bool:
        """Cancel queued work and wait for every managed QThread to finish.

        ``BackgroundWorker.cancel`` is cooperative and cannot interrupt a
        blocking network call. Keeping the worker references and reporting a
        timeout lets the window postpone closing instead of destroying a live
        ``QThread`` and aborting the process.
        """
        for jobs in self._queues.values():
            for job in jobs:
                if job.handle is not None:
                    job.handle.cancel()
            jobs.clear()

        workers: list[BackgroundWorker] = []
        seen: set[int] = set()
        for active in self._active.values():
            for worker in active:
                if id(worker) in seen or not worker.isRunning():
                    continue
                seen.add(id(worker))
                workers.append(worker)
                worker.cancel()

        deadline = time.monotonic() + max(int(wait_ms), 0) / 1000.0
        for worker in workers:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if worker.isRunning() and not worker.wait(remaining_ms):
                logger.warning("Background worker still running during application shutdown")
                return False

        for queue_name in list(self._active):
            self._prune_finished(queue_name)
        return True

    def _drop_pending(self, queue: str, key: str, *, cancel: bool = False) -> None:
        jobs = self._queues.get(queue, [])
        kept: list[_QueuedJob] = []
        for job in jobs:
            if job.coalesce_key == key:
                if cancel and job.handle is not None:
                    job.handle.cancel()
                continue
            kept.append(job)
        self._queues[queue] = kept

    def _sort_queue(self, queue: str) -> None:
        self._queues.setdefault(queue, []).sort(key=lambda job: (job.priority, job.order))

    def _try_start(self, queue: str) -> None:
        self._prune_finished(queue)
        limit = self._queue_limits.get(queue, self._queue_limits["default"])
        while self.active_count(queue) < limit:
            jobs = self._queues.get(queue, [])
            if not jobs:
                return
            started = False
            for index, job in enumerate(list(jobs)):
                if job.owner_ref is not None and job.owner_ref() is None:
                    del jobs[index]
                    started = True
                    break
                if job.can_start is not None and not job.can_start():
                    continue
                worker = job.start_fn()
                del jobs[index]
                if worker is None:
                    QTimer.singleShot(0, lambda q=queue: self._try_start(q))
                    return
                self._active.setdefault(queue, []).append(worker)
                self._active_jobs.setdefault(queue, []).append(job)
                if job.handle is not None:
                    job.handle.worker = worker
                    job.handle.started_at = time.perf_counter()
                    queued_ms = int((job.handle.started_at - job.handle.queued_at) * 1000)
                    logger.debug("Background job start queue=%s key=%s queued_ms=%s", queue, job.coalesce_key, queued_ms)
                worker.signals.finished.connect(lambda q=queue, w=worker: self._on_worker_finished(q, w))
                worker.start()
                started = True
                break
            if not started:
                return

    def _on_worker_finished(self, queue: str, worker: BackgroundWorker) -> None:
        jobs = self._active_jobs.get(queue, [])
        matched: _QueuedJob | None = None
        for job in list(jobs):
            if job.handle is not None and job.handle.worker is worker:
                matched = job
                break
        if matched is not None and matched.handle is not None:
            matched.handle.finished_at = time.perf_counter()
            elapsed_ms = int((matched.handle.finished_at - matched.handle.started_at) * 1000) if matched.handle.started_at else 0
            logger.debug("Background job finished queue=%s key=%s elapsed_ms=%s", queue, matched.coalesce_key, elapsed_ms)
        self._prune_finished(queue)
        QTimer.singleShot(0, lambda q=queue: self._try_start(q))

    def _prune_finished(self, queue: str) -> None:
        active = [worker for worker in self._active.get(queue, []) if worker.isRunning()]
        self._active[queue] = active
        self._active_jobs[queue] = [
            job
            for job in self._active_jobs.get(queue, [])
            if job.handle is None or job.handle.worker in active
        ]

    @staticmethod
    def _owner_alive(owner_ref: weakref.ReferenceType[QObject] | None, owner: QObject) -> bool:
        return owner_ref is not None and owner_ref() is owner
