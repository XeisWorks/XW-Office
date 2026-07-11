"""Thread-safe background worker using QThread + signals."""
from __future__ import annotations

import logging
from threading import Event
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Signals emitted by BackgroundWorker."""
    started = Signal()
    progress = Signal(int, str)
    result = Signal(object)
    error = Signal(Exception)
    finished = Signal()


class BackgroundWorker(QThread):
    """Run a callable in a background thread with progress reporting.

    Usage::

        worker = BackgroundWorker(some_function, arg1, arg2)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.start()
    """

    signals: WorkerSignals

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._cancelled = Event()

    def cancel(self) -> None:
        """Request cancellation and suppress a result that arrives afterwards.

        Python callables cannot be stopped safely from the outside. Long-running
        services may additionally inspect :attr:`cancelled`; regardless of that,
        a cancelled worker never publishes a stale result to the UI.
        """
        self._cancelled.set()
        self.requestInterruption()

    @property
    def cancelled(self) -> bool:
        """Return whether cancellation was requested."""
        return self._cancelled.is_set() or self.isInterruptionRequested()

    def run(self) -> None:
        self.signals.started.emit()
        try:
            result = self._fn(*self._args, **self._kwargs)
            if not self.cancelled:
                self.signals.result.emit(result)
        except Exception as exc:
            if not self.cancelled:
                logger.error("Worker error: %s\n%s", exc, traceback.format_exc())
                self.signals.error.emit(exc)
        finally:
            self.signals.finished.emit()
