from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from xw_studio.services.printing.pdf_backends import (
    NativePdfCliBackend,
    QtRasterBackend,
    backend_for_job,
)
from xw_studio.services.printing.print_jobs import PdfPrintJob


def test_qt_raster_remains_the_default_backend() -> None:
    job = PdfPrintJob(pdf_path="C:/tmp/test.pdf", printer_name="Printer")

    assert isinstance(backend_for_job(job), QtRasterBackend)


def test_pdf_xchange_builds_silent_native_command_with_pages_and_copies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "PXCEditor.exe"
    executable.write_bytes(b"test")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-test")
    pages_pdf = tmp_path / "pages.pdf"
    pages_pdf.write_bytes(b"%PDF-pages")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends._extract_pdf_pages",
        lambda _pdf_path, _pages: str(pages_pdf),
    )
    monkeypatch.setattr("xw_studio.services.printing.pdf_backends._windows_print_job_snapshot", lambda _printer: "")
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends._wait_for_spooler_change",
        lambda _printer, previous_snapshot: '{"ID":1,"DocumentName":"sample.pdf","JobStatus":"Printing"}',
    )
    job = PdfPrintJob(
        pdf_path=str(pdf),
        printer_name="Noten A4 Simplex",
        pages=[0, 1, 3, 4, 6],
        copies=2,
        backend="pdf_xchange",
        native_pdf_exe=str(executable),
    )

    backend_for_job(job).print(job)

    assert len(calls) == 2
    assert calls[0] == [str(executable), "/printto", "Noten A4 Simplex", str(pages_pdf)]

    windows_command_line = subprocess.list2cmdline(calls[0])
    assert "/print:" not in windows_command_line
    assert "/printto" in windows_command_line


def test_pdf_xchange_uses_registered_printto_command_for_full_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "PXCEditor.exe"
    executable.write_bytes(b"test")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-test")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("xw_studio.services.printing.pdf_backends._windows_print_job_snapshot", lambda _printer: "")
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends._wait_for_spooler_change",
        lambda _printer, previous_snapshot: '{"ID":1,"DocumentName":"sample.pdf","JobStatus":"Printing"}',
    )

    job = PdfPrintJob(
        pdf_path=str(pdf),
        printer_name="Noten A4 Duplex",
        backend="pdf_xchange",
        native_pdf_exe=str(executable),
    )
    backend_for_job(job).print(job)

    assert calls[0] == [str(executable), "/printto", "Noten A4 Duplex", str(pdf)]


def test_pdf_xchange_without_visible_spooler_job_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "PXCEditor.exe"
    executable.write_bytes(b"test")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-test")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )
    monkeypatch.setattr("xw_studio.services.printing.pdf_backends._windows_print_job_snapshot", lambda _printer: "")
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends._wait_for_spooler_change",
        lambda _printer, previous_snapshot: "",
    )

    NativePdfCliBackend(str(executable)).print(
        PdfPrintJob(
            pdf_path=str(pdf),
            printer_name="Noten A4 Duplex",
            backend="pdf_xchange",
            native_pdf_exe=str(executable),
        )
    )


def test_pdf_xchange_missing_executable_uses_acrobat_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qt_calls: list[object] = []
    popen_calls: list[list[str]] = []
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends.print_pdf_with_qprinter",
        lambda *args, **kwargs: qt_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends._acrobat_executable",
        lambda: str(tmp_path / "Acrobat.exe"),
    )
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends._windows_printer_driver_port",
        lambda _printer: {"driver": "Driver", "port": "Port"},
    )
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **_kwargs: popen_calls.append(command),
    )
    job = PdfPrintJob(
        pdf_path=str(tmp_path / "sample.pdf"),
        printer_name="Printer",
        backend="pdf_xchange",
        native_pdf_exe=str(tmp_path / "missing.exe"),
    )
    Path(job.pdf_path).write_bytes(b"%PDF-test")

    backend_for_job(job).print(job)

    assert qt_calls == []
    assert popen_calls == [[str(tmp_path / "Acrobat.exe"), "/t", job.pdf_path, "Printer", "Driver", "Port"]]


def test_pdf_xchange_nonzero_exit_uses_acrobat_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "PDFXEdit.exe"
    executable.write_bytes(b"test")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-test")
    popen_calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 5, "", "driver error"),
    )
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends._acrobat_executable",
        lambda: str(tmp_path / "Acrobat.exe"),
    )
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends._windows_printer_driver_port",
        lambda _printer: {},
    )
    monkeypatch.setattr(subprocess, "Popen", lambda command, **_kwargs: popen_calls.append(command))
    monkeypatch.setattr("xw_studio.services.printing.pdf_backends._windows_print_job_snapshot", lambda _printer: "")

    NativePdfCliBackend(str(executable)).print(
        PdfPrintJob(
            pdf_path=str(pdf),
            printer_name="Printer",
            backend="pdf_xchange",
            native_pdf_exe=str(executable),
        )
    )

    assert popen_calls == [[str(tmp_path / "Acrobat.exe"), "/t", str(pdf), "Printer"]]
