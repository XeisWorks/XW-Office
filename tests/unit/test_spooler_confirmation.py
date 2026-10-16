"""Invoice/label dispatch must fail closed when the Windows spooler is unavailable."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from xw_office.services.printing import pdf_backends, print_queue
from xw_office.services.printing.print_jobs import BrotherLbxLabelJob, PdfPrintJob


@pytest.mark.parametrize("kind", ["invoice", "label"])
@pytest.mark.parametrize("failure", ["offline", "missing_confirmation", "driver", "none"])
def test_dispatch_requires_ready_printer_and_spooler_confirmation(
    monkeypatch: pytest.MonkeyPatch, kind: str, failure: str,
) -> None:
    spooler = MagicMock()
    spooler.__enter__.return_value = spooler
    spooler.wait.return_value = failure != "missing_confirmation"
    if failure == "offline":
        spooler.check_ready.side_effect = RuntimeError("Drucker offline")
    dispatch = MagicMock()
    if failure == "driver":
        dispatch.side_effect = RuntimeError("Treiberfehler")
    monkeypatch.setattr(pdf_backends, "sys", SimpleNamespace(platform="win32"))
    watcher = MagicMock(return_value=spooler)
    monkeypatch.setattr(pdf_backends, "_WindowsSpoolerWatcher", watcher)
    monkeypatch.setattr(pdf_backends, "print_pdf_with_qprinter", dispatch)
    monkeypatch.setattr(print_queue, "_execute_brother_lbx_job", dispatch)
    job = (
        PdfPrintJob(pdf_path="invoice.pdf", printer_name="Printer", job_kind="invoice")
        if kind == "invoice"
        else BrotherLbxLabelJob(printer_name="Printer", template_path="label.lbx", lines=["Test"])
    )

    if failure == "none":
        print_queue._PrintQueueWorker._execute(job)
        assert spooler.check_ready.call_count == 2
    else:
        with pytest.raises(RuntimeError):
            print_queue._PrintQueueWorker._execute(job)
    watcher.assert_called_once_with("Printer")
    spooler.__exit__.assert_called_once()
    assert dispatch.call_count == (0 if failure == "offline" else 1)
    assert spooler.wait.call_count == (0 if failure in {"offline", "driver"} else 1)


@pytest.mark.parametrize(
    ("status", "attributes", "blocked"),
    [(0, 0, False), (0x400, 0, False), (1, 0, True), (2, 0, True),
     (0x80, 0, True), (0, 0x400, True)],
)
def test_spooler_status_rejects_paused_error_and_offline_queues(
    status: int, attributes: int, blocked: bool,
) -> None:
    watcher = object.__new__(pdf_backends._WindowsSpoolerWatcher)
    watcher._printer_name = "Printer"
    watcher._printer_handle = object()
    watcher._win32print = MagicMock()
    watcher._win32print.GetPrinter.return_value = {"Status": status, "Attributes": attributes}
    if blocked:
        with pytest.raises(RuntimeError, match="Windows-Druckwarteschlange"):
            watcher.check_ready()
    else:
        watcher.check_ready()


def test_spooler_status_read_failure_is_user_facing() -> None:
    watcher = object.__new__(pdf_backends._WindowsSpoolerWatcher)
    watcher._printer_name = "Printer"
    watcher._printer_handle = object()
    watcher._win32print = MagicMock()
    watcher._win32print.GetPrinter.side_effect = OSError("Spooler stopped")
    with pytest.raises(RuntimeError, match="Spooler stopped"):
        watcher.check_ready()
