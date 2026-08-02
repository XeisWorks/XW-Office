"""Reusable non-blocking UI action controller."""
from __future__ import annotations

from collections.abc import Callable
import logging
import time
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

from xw_office.core.worker import BackgroundWorker

logger = logging.getLogger(__name__)


class UiAsyncAction(QObject):
    """Own one latest-wins worker and restore its UI state reliably."""

    def __init__(
        self,
        owner: QWidget,
        *,
        button: QAbstractButton | None = None,
        status_label: QLabel | None = None,
        idle_text: str | None = None,
    ) -> None:
        super().__init__(owner)
        self._owner = owner
        self._button = button
        self._status_label = status_label
        self._idle_text = idle_text if idle_text is not None else (button.text() if button else "")
        self._worker: BackgroundWorker | None = None
        self._generation = 0
        self._started_at = 0.0
        self._action_name = ""

    @property
    def worker(self) -> BackgroundWorker | None:
        """Expose the active worker for shutdown and compatibility checks."""
        return self._worker

    def is_running(self) -> bool:
        """Return whether the current worker is active."""
        return bool(self._worker is not None and self._worker.isRunning())

    def cancel(self) -> None:
        """Invalidate the current generation and suppress its eventual result."""
        self._generation += 1
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()

    def start(
        self,
        fn: Callable[[], Any],
        *,
        action_name: str,
        busy_text: str,
        on_result: Callable[[object], None],
        on_error: Callable[[Exception], None] | None = None,
        replace_running: bool = False,
    ) -> bool:
        """Start work after applying immediate feedback.

        With ``replace_running=True``, an older result is invalidated and the new
        worker starts immediately. The caller should only use this for services
        that permit concurrent reads.
        """
        if self.is_running():
            if not replace_running:
                return False
            self.cancel()

        self._generation += 1
        generation = self._generation
        self._action_name = action_name
        self._started_at = time.perf_counter()
        self._set_busy(True, busy_text)

        worker = BackgroundWorker(fn)
        self._worker = worker
        worker.signals.result.connect(
            lambda payload, token=generation: self._deliver_result(token, payload, on_result)
        )
        if on_error is not None:
            worker.signals.error.connect(
                lambda exc, token=generation: self._deliver_error(token, exc, on_error)
            )
        worker.signals.finished.connect(
            lambda token=generation, current=worker: self._finish(token, current)
        )
        worker.start()
        return True

    def _deliver_result(
        self,
        generation: int,
        payload: object,
        callback: Callable[[object], None],
    ) -> None:
        if generation != self._generation:
            return
        callback(payload)

    def _deliver_error(
        self,
        generation: int,
        exc: Exception,
        callback: Callable[[Exception], None],
    ) -> None:
        if generation != self._generation:
            return
        callback(exc)

    def _finish(self, generation: int, worker: BackgroundWorker) -> None:
        if self._worker is worker:
            self._worker = None
        if generation != self._generation:
            return
        elapsed_ms = int((time.perf_counter() - self._started_at) * 1000)
        logger.info("ui_action=%s elapsed_ms=%s", self._action_name, elapsed_ms)
        self._set_busy(False, "")

    def _set_busy(self, busy: bool, text: str) -> None:
        if self._button is not None:
            self._button.setEnabled(not busy)
            self._button.setText(text if busy else self._idle_text)
        if busy and self._status_label is not None:
            self._status_label.setText(text)
