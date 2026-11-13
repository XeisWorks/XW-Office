"""Central sequential non-blocking print queue."""
from __future__ import annotations

import logging
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from typing import TypeAlias

from PySide6.QtCore import QObject, QThread, Signal

from xw_office.services.printing.pdf_backends import backend_for_job
from xw_office.services.printing.print_jobs import BrotherLbxLabelJob, PdfPrintJob, PrintJobResult

logger = logging.getLogger(__name__)

PrintJob: TypeAlias = PdfPrintJob | BrotherLbxLabelJob


def _delete_paths(paths: tuple[str, ...]) -> None:
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def _execute_brother_lbx_job(job: BrotherLbxLabelJob) -> None:
    """Run bPAC on a fresh main thread; its COM activation can hang in QThread."""
    payload = {
        "printer_name": job.printer_name,
        "template_path": job.template_path,
        "lines": job.lines,
        "overlay_object": job.overlay_object,
        "overlay_text": job.overlay_text,
        "description": job.description,
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "xw_office.services.printing.bpac_worker"],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Brother bPAC reagiert seit 60 Sekunden nicht") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:300]
        raise RuntimeError(detail or f"Brother bPAC fehlgeschlagen (Code {result.returncode})")


def _print_brother_lbx_direct(job: BrotherLbxLabelJob) -> None:
    pythoncom_mod = None
    try:
        import pythoncom  # type: ignore[import-untyped]  # COM bindings do not ship stubs.
        import win32com.client  # type: ignore[import-untyped]  # COM bindings do not ship stubs.

        pythoncom_mod = pythoncom
    except ImportError as exc:
        raise RuntimeError("Etikettendruck erfordert Windows (pywin32).") from exc

    temp_path = ""
    doc = None
    pythoncom_mod.CoInitialize()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".lbx") as handle:
            temp_path = handle.name
        shutil.copyfile(job.template_path, temp_path)

        logger.info("Brother bPAC stage=dispatch")
        doc = win32com.client.Dispatch("bpac.Document")
        logger.info("Brother bPAC stage=open")
        if not bool(doc.Open(temp_path)):
            raise RuntimeError("LBX konnte nicht geladen werden")

        logger.info("Brother bPAC stage=recipient")
        obj = doc.GetObject("Empfaenger")
        if not obj:
            raise RuntimeError("LBX-Objekt 'Empfaenger' nicht gefunden")
        obj.Text = "\r\n".join(str(line) for line in job.lines)

        if job.overlay_object:
            overlay = doc.GetObject(job.overlay_object)
            if not overlay:
                raise RuntimeError(f"LBX-Objekt '{job.overlay_object}' nicht gefunden")
            if job.overlay_text is not None:
                overlay.Text = job.overlay_text

        logger.info("Brother bPAC stage=set_printer")
        if not doc.SetPrinter(job.printer_name, True):
            raise RuntimeError("Etikettendrucker nicht gefunden")
        if hasattr(doc, "SetMediaByName"):
            try:
                doc.SetMediaByName("DK-11202")
            except Exception:
                pass
        if hasattr(doc, "StartPrint") and callable(doc.StartPrint):
            logger.info("Brother bPAC stage=start_print")
            if not bool(doc.StartPrint(job.description or "Address Label", 0)):
                raise RuntimeError("StartPrint fehlgeschlagen")
        if not hasattr(doc, "PrintOut"):
            raise RuntimeError("Etikettendruck fehlgeschlagen")
        logger.info("Brother bPAC stage=print_out")
        ok = doc.PrintOut(1, 0) if callable(doc.PrintOut) else bool(doc.PrintOut)
        if not ok:
            raise RuntimeError("Etikettendruck fehlgeschlagen")
        if hasattr(doc, "EndPrint") and callable(doc.EndPrint):
            logger.info("Brother bPAC stage=end_print")
            doc.EndPrint()
        logger.info("Brother bPAC stage=complete")
    finally:
        if doc is not None and callable(getattr(doc, "Close", None)):
            try:
                doc.Close()
            except Exception:
                pass
        if temp_path:
            _delete_paths((temp_path,))
        if pythoncom_mod is not None:
            pythoncom_mod.CoUninitialize()


class _PrintQueueWorker(QThread):
    job_started = Signal(object)
    job_finished = Signal(object)
    job_failed = Signal(object)

    def __init__(
        self,
        jobs: "queue.Queue[PrintJob | None]",
        result_callback: Callable[[PrintJobResult], None] | None = None,
        active_job_callback: Callable[[PrintJob | None, float | None], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._jobs = jobs
        self._result_callback = result_callback
        self._active_job_callback = active_job_callback
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True
        self._jobs.put(None)

    def run(self) -> None:
        while not self._stopping:
            job = self._jobs.get()
            if job is None:
                self._jobs.task_done()
                break
            started_at = time.perf_counter()
            if self._active_job_callback is not None:
                self._active_job_callback(job, started_at)
            self.job_started.emit(job)
            outcome = "error"
            try:
                self._execute(job)
            except Exception as exc:  # noqa: BLE001
                result = PrintJobResult(
                    job_id=job.id,
                    success=False,
                    description=getattr(job, "description", "") or getattr(job, "source_name", ""),
                    printer_name=getattr(job, "printer_name", ""),
                    message=str(exc),
                )
                logger.exception("Print job failed: %s", result)
                if self._result_callback is not None:
                    self._result_callback(result)
                self.job_failed.emit(result)
            else:
                outcome = "success"
                result = PrintJobResult(
                    job_id=job.id,
                    success=True,
                    description=getattr(job, "description", "") or getattr(job, "source_name", ""),
                    printer_name=getattr(job, "printer_name", ""),
                    message="dispatched",
                )
                if self._result_callback is not None:
                    self._result_callback(result)
                self.job_finished.emit(result)
            finally:
                logger.info(
                    "Print job metric id=%s kind=%s backend=%s elapsed_ms=%s outcome=%s",
                    job.id,
                    job.job_kind if isinstance(job, PdfPrintJob) else "address_label",
                    job.backend if isinstance(job, PdfPrintJob) else "brother_bpac",
                    int((time.perf_counter() - started_at) * 1000),
                    outcome,
                )
                if self._active_job_callback is not None:
                    self._active_job_callback(None, None)
                if isinstance(job, PdfPrintJob) and job.cleanup_paths:
                    _delete_paths(job.cleanup_paths)
                self._jobs.task_done()

    @staticmethod
    def _execute(job: PrintJob) -> None:
        if isinstance(job, PdfPrintJob):
            logger.info(
                "Print job started: id=%s kind=%s printer='%s' file='%s' copies=%s dpi=%s pages=%s "
                "placement=%s page_size=%s orientation=%s scale_mode=%s scale_percent=%s alignment=%s offset_mm=(%s,%s) "
                "rotate_degrees=%s "
                "render_color_mode=%s black_enhancement=%s black_threshold=%s backend=%s",
                job.id,
                job.job_kind,
                job.printer_name,
                job.pdf_path,
                job.copies,
                job.dpi if job.dpi is not None else f"queue-default/fallback-{job.effective_dpi}",
                job.pages,
                job.placement_mode,
                job.page_size,
                job.orientation,
                job.scale_mode,
                job.scale_percent,
                job.alignment,
                job.x_offset_mm,
                job.y_offset_mm,
                job.rotate_degrees,
                job.effective_render_color_mode,
                job.effective_black_enhancement,
                job.black_threshold,
                job.backend,
            )
            backend_for_job(job).print(job)
            return
        _execute_brother_lbx_job(job)


class PrintQueueService(QObject):
    job_queued = Signal(object)
    job_started = Signal(object)
    job_finished = Signal(object)
    job_failed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: queue.Queue[PrintJob | None] = queue.Queue()
        self._worker: _PrintQueueWorker | None = None
        self._worker_lock = threading.RLock()
        self._active_job_lock = threading.Lock()
        self._active_job: tuple[PrintJob, float] | None = None
        self._stopping = False
        self._result_condition = threading.Condition()
        self._awaited_job_ids: set[str] = set()
        self._results: dict[str, PrintJobResult] = {}

    def _ensure_worker(self) -> _PrintQueueWorker:
        with self._worker_lock:
            if self._stopping:
                raise RuntimeError("Print queue is shutting down")
            if self._worker is None or not self._worker.isRunning():
                self._worker = _PrintQueueWorker(
                    self._jobs,
                    self._record_result,
                    self._set_active_job,
                )
                self._worker.job_started.connect(self.job_started.emit)
                self._worker.job_finished.connect(self.job_finished.emit)
                self._worker.job_failed.connect(self.job_failed.emit)
                self._worker.start()
            return self._worker

    def _set_active_job(self, job: PrintJob | None, started_at: float | None) -> None:
        with self._active_job_lock:
            self._active_job = (job, started_at) if job is not None and started_at is not None else None

    def active_job_context(self) -> str | None:
        """Return a compact, thread-safe label for UI performance diagnostics."""
        with self._active_job_lock:
            active = self._active_job
        if active is None:
            return None
        job, started_at = active
        kind = job.job_kind if isinstance(job, PdfPrintJob) else "address_label"
        backend = job.backend if isinstance(job, PdfPrintJob) else "brother_bpac"
        elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        return f"id={job.id} kind={kind} backend={backend} active_ms={elapsed_ms}"

    def enqueue(self, job: PrintJob) -> str:
        with self._worker_lock:
            self._ensure_worker()
            self._jobs.put(job)
        self.job_queued.emit(job)
        logger.info("Print job queued: id=%s printer='%s'", job.id, getattr(job, "printer_name", ""))
        return job.id

    def enqueue_and_wait(self, job: PrintJob, *, timeout_seconds: float = 300.0) -> PrintJobResult:
        """Queue one job and wait until the print backend reports success or failure."""
        timeout = max(float(timeout_seconds), 0.1)
        with self._result_condition:
            self._awaited_job_ids.add(job.id)
        self.enqueue(job)
        deadline = time.monotonic() + timeout
        with self._result_condition:
            while job.id not in self._results:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._awaited_job_ids.discard(job.id)
                    raise TimeoutError(
                        f"Druckjob {job.id} wurde nach {timeout:.0f} Sekunden nicht bestaetigt"
                    )
                self._result_condition.wait(remaining)
            result = self._results.pop(job.id)
            self._awaited_job_ids.discard(job.id)
        return result

    def _record_result(self, result: PrintJobResult) -> None:
        with self._result_condition:
            if result.job_id not in self._awaited_job_ids:
                return
            self._results[result.job_id] = result
            self._result_condition.notify_all()

    def shutdown(self, wait_ms: int = 5000) -> bool:
        """Stop the queue thread, returning false while a backend is still busy."""
        with self._worker_lock:
            self._stopping = True
            if self._worker is not None and self._worker.isRunning():
                self._worker.stop()
                if not self._worker.wait(max(int(wait_ms), 0)):
                    logger.warning("Print queue worker still running during application shutdown")
                    return False
            self._worker = None
            return True

    def __del__(self) -> None:
        try:
            self.shutdown(1000)
        except Exception:
            pass


_GLOBAL_QUEUE: PrintQueueService | None = None


def global_print_queue() -> PrintQueueService:
    global _GLOBAL_QUEUE
    if _GLOBAL_QUEUE is None:
        _GLOBAL_QUEUE = PrintQueueService()
    return _GLOBAL_QUEUE
