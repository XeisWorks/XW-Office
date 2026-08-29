from __future__ import annotations

import threading
import types
from unittest.mock import MagicMock

from xw_office.services.printing import print_queue
from xw_office.services.printing import pdf_backends
from xw_office.services.printing.print_jobs import BrotherLbxLabelJob, PdfPrintJob, PrintJobResult


def test_print_queue_worker_executes_jobs_sequentially(monkeypatch) -> None:
    calls: list[str] = []
    pdf_kwargs: dict[str, object] = {}

    def fake_pdf(*_args: object, **kwargs: object) -> None:
        calls.append("pdf")
        pdf_kwargs.update(kwargs)

    def fake_lbx(_job: BrotherLbxLabelJob) -> None:
        calls.append("lbx")

    monkeypatch.setattr(pdf_backends, "print_pdf_with_qprinter", fake_pdf)
    monkeypatch.setattr(print_queue, "_execute_brother_lbx_job", fake_lbx)

    print_queue._PrintQueueWorker._execute(PdfPrintJob(pdf_path="a.pdf", printer_name="P"))
    print_queue._PrintQueueWorker._execute(
        BrotherLbxLabelJob(printer_name="L", template_path="t.lbx", lines=["A"])
    )

    assert calls == ["pdf", "lbx"]
    assert pdf_kwargs["dpi"] is None
    assert pdf_kwargs["fallback_dpi"] == 600
    assert pdf_kwargs["placement_mode"] == "paper_origin"
    assert pdf_kwargs["x_offset_mm"] == 0.0
    assert pdf_kwargs["y_offset_mm"] == 0.0
    assert pdf_kwargs.get("rotate_degrees", 0) == 0
    assert pdf_kwargs["render_color_mode"] == "auto"
    assert pdf_kwargs["black_enhancement"] == "auto_music"
    assert pdf_kwargs["black_threshold"] == 180


def test_brother_lbx_job_initializes_and_uninitializes_com(monkeypatch, tmp_path) -> None:
    template = tmp_path / "template.lbx"
    template.write_text("template", encoding="utf-8")
    events: list[str] = []

    pythoncom = types.SimpleNamespace(
        CoInitialize=lambda: events.append("init"),
        CoUninitialize=lambda: events.append("uninit"),
    )

    doc = MagicMock()
    doc.Open.return_value = True
    doc.GetObject.return_value = MagicMock()
    doc.SetPrinter.return_value = True
    doc.StartPrint.return_value = True
    doc.PrintOut.return_value = True
    win32com_client = types.SimpleNamespace(Dispatch=lambda _name: doc)

    monkeypatch.setitem(__import__("sys").modules, "pythoncom", pythoncom)
    monkeypatch.setitem(__import__("sys").modules, "win32com", types.SimpleNamespace(client=win32com_client))
    monkeypatch.setitem(__import__("sys").modules, "win32com.client", win32com_client)

    print_queue._execute_brother_lbx_job(
        BrotherLbxLabelJob(printer_name="Brother", template_path=str(template), lines=["Line 1"])
    )

    assert events == ["init", "uninit"]
    doc.SetPrinter.assert_called_once_with("Brother", True)


def test_enqueue_and_wait_returns_worker_result(monkeypatch) -> None:
    service = print_queue.PrintQueueService()
    job = PdfPrintJob(pdf_path="a.pdf", printer_name="P")

    def fake_enqueue(queued_job: PdfPrintJob) -> str:
        threading.Thread(
            target=lambda: service._record_result(  # noqa: SLF001
                PrintJobResult(
                    job_id=queued_job.id,
                    success=True,
                    description="test",
                    printer_name="P",
                    message="dispatched",
                )
            )
        ).start()
        return queued_job.id

    monkeypatch.setattr(service, "enqueue", fake_enqueue)

    result = service.enqueue_and_wait(job, timeout_seconds=1)

    assert result.success is True
    assert result.job_id == job.id


def test_idle_print_queue_thread_stops_cleanly() -> None:
    service = print_queue.PrintQueueService()
    worker = service._ensure_worker()  # noqa: SLF001

    assert worker.isRunning()
    assert service.shutdown(1000) is True
    assert worker.isRunning() is False
