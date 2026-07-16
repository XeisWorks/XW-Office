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
    executable = tmp_path / "PDFXEdit.exe"
    executable.write_bytes(b"test")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-test")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
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
    assert calls[0] == [
        str(executable),
        '/print:default=yes;showui=no;printer="Noten A4 Simplex";pages=1-2,4-5,7',
        str(pdf),
    ]


def test_pdf_xchange_missing_executable_fails_without_qt_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qt_calls: list[object] = []
    monkeypatch.setattr(
        "xw_studio.services.printing.pdf_backends.print_pdf_with_qprinter",
        lambda *args, **kwargs: qt_calls.append((args, kwargs)),
    )
    job = PdfPrintJob(
        pdf_path=str(tmp_path / "sample.pdf"),
        printer_name="Printer",
        backend="pdf_xchange",
        native_pdf_exe=str(tmp_path / "missing.exe"),
    )

    with pytest.raises(RuntimeError, match="EXE wurde nicht gefunden"):
        backend_for_job(job).print(job)

    assert qt_calls == []


def test_pdf_xchange_nonzero_exit_is_a_print_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "PDFXEdit.exe"
    executable.write_bytes(b"test")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-test")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 5, "", "driver error"),
    )

    with pytest.raises(RuntimeError, match="Exit-Code 5.*driver error"):
        NativePdfCliBackend(str(executable)).print(
            PdfPrintJob(pdf_path=str(pdf), printer_name="Printer")
        )
