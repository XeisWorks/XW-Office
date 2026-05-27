"""Central sequential non-blocking print queue."""
from __future__ import annotations

import logging
import os
import queue
import shutil
import tempfile
from typing import TypeAlias

from PySide6.QtCore import QObject, QThread, Signal

from xw_studio.services.printing.pdf_renderer import print_pdf_with_qprinter
from xw_studio.services.printing.print_jobs import BrotherLbxLabelJob, PdfPrintJob, PrintJobResult

logger = logging.getLogger(__name__)

PrintJob: TypeAlias = PdfPrintJob | BrotherLbxLabelJob


def _delete_paths(paths: tuple[str, ...]) -> None:
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def _execute_brother_lbx_job(job: BrotherLbxLabelJob) -> None:
    pythoncom_mod = None
    try:
        import pythoncom  # type: ignore[import-untyped]
        import win32com.client  # type: ignore[import-untyped]

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

        doc = win32com.client.Dispatch("bpac.Document")
        if not bool(doc.Open(temp_path)):
            raise RuntimeError("LBX konnte nicht geladen werden")

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

        if not doc.SetPrinter(job.printer_name, True):
            raise RuntimeError("Etikettendrucker nicht gefunden")
        if hasattr(doc, "SetMediaByName"):
            try:
                doc.SetMediaByName("DK-11202")
            except Exception:
                pass
        if hasattr(doc, "StartPrint") and callable(doc.StartPrint):
            if not bool(doc.StartPrint(job.description or "Address Label", 0)):
                raise RuntimeError("StartPrint fehlgeschlagen")
        if not hasattr(doc, "PrintOut"):
            raise RuntimeError("Etikettendruck fehlgeschlagen")
        ok = doc.PrintOut(False, False) if callable(doc.PrintOut) else bool(doc.PrintOut)
        if not ok:
            raise RuntimeError("Etikettendruck fehlgeschlagen")
        if hasattr(doc, "EndPrint") and callable(doc.EndPrint):
            doc.EndPrint()
    finally:
        if doc is not None:
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

    def __init__(self, jobs: "queue.Queue[PrintJob | None]", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs = jobs
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
            self.job_started.emit(job)
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
                self.job_failed.emit(result)
            else:
                result = PrintJobResult(
                    job_id=job.id,
                    success=True,
                    description=getattr(job, "description", "") or getattr(job, "source_name", ""),
                    printer_name=getattr(job, "printer_name", ""),
                    message="dispatched",
                )
                self.job_finished.emit(result)
            finally:
                if isinstance(job, PdfPrintJob) and job.cleanup_paths:
                    _delete_paths(job.cleanup_paths)
                self._jobs.task_done()

    @staticmethod
    def _execute(job: PrintJob) -> None:
        if isinstance(job, PdfPrintJob):
            logger.info(
                "Print job started: id=%s kind=%s printer='%s' file='%s' copies=%s dpi=%s pages=%s "
                "placement=%s offset_mm=(%s,%s)",
                job.id,
                job.job_kind,
                job.printer_name,
                job.pdf_path,
                job.copies,
                job.dpi if job.dpi is not None else f"queue-default/fallback-{job.effective_dpi}",
                job.pages,
                job.placement_mode,
                job.x_offset_mm,
                job.y_offset_mm,
            )
            print_pdf_with_qprinter(
                job.pdf_path,
                job.printer_name,
                pages=job.pages,
                copies=job.copies,
                dpi=job.dpi,
                fallback_dpi=job.effective_dpi,
                placement_mode=job.placement_mode,
                x_offset_mm=job.x_offset_mm,
                y_offset_mm=job.y_offset_mm,
                job_kind=job.job_kind,
            )
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

    def _ensure_worker(self) -> _PrintQueueWorker:
        if self._worker is None or not self._worker.isRunning():
            self._worker = _PrintQueueWorker(self._jobs)
            self._worker.job_started.connect(self.job_started.emit)
            self._worker.job_finished.connect(self.job_finished.emit)
            self._worker.job_failed.connect(self.job_failed.emit)
            self._worker.start()
        return self._worker

    def enqueue(self, job: PrintJob) -> str:
        self._ensure_worker()
        self._jobs.put(job)
        self.job_queued.emit(job)
        logger.info("Print job queued: id=%s printer='%s'", job.id, getattr(job, "printer_name", ""))
        return job.id

    def shutdown(self, wait_ms: int = 5000) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(wait_ms)
        self._worker = None

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
