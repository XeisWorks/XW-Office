from __future__ import annotations

from pathlib import Path
import subprocess

import fitz
import pytest

from xw_office.services.printing.pdf_backends import (
    NativePdfCliBackend,
    QtRasterBackend,
    backend_for_job,
)
from xw_office.services.printing.print_jobs import PdfPrintJob


class _FakeSpoolerWatcher:
    def __init__(self, _printer_name: str, *, confirmed: bool = True) -> None:
        self.confirmed = confirmed

    def __enter__(self) -> "_FakeSpoolerWatcher":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def wait(self, *, timeout_seconds: float) -> bool:
        assert timeout_seconds > 0
        return self.confirmed


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
        "xw_office.services.printing.pdf_backends._extract_pdf_pages",
        lambda _pdf_path, _pages, **_kwargs: str(pages_pdf),
    )
    monkeypatch.setattr("xw_office.services.printing.pdf_backends._WindowsSpoolerWatcher", _FakeSpoolerWatcher)
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
        "/printto:default=yes;showui=no",
        "Noten A4 Simplex",
        str(pages_pdf),
    ]

    windows_command_line = subprocess.list2cmdline(calls[0])
    assert "/printto:default=yes;showui=no" in windows_command_line


def test_pdf_xchange_uses_explicit_silent_printer_for_full_document(
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
    monkeypatch.setattr("xw_office.services.printing.pdf_backends._WindowsSpoolerWatcher", _FakeSpoolerWatcher)

    job = PdfPrintJob(
        pdf_path=str(pdf),
        printer_name="Noten A4 Duplex",
        backend="pdf_xchange",
        native_pdf_exe=str(executable),
    )
    backend_for_job(job).print(job)

    assert calls[0] == [
        str(executable),
        "/printto:default=yes;showui=no",
        "Noten A4 Duplex",
        str(pdf),
    ]


def test_pdf_xchange_command_keeps_each_plan_printer_explicit() -> None:
    from xw_office.services.printing.pdf_backends import _pdf_xchange_print_command

    first = _pdf_xchange_print_command("PDFXEdit.exe", "Simplex", "score.pdf")
    second = _pdf_xchange_print_command("PDFXEdit.exe", "Duplex", "score.pdf")

    assert first[1:] == ["/printto:default=yes;showui=no", "Simplex", "score.pdf"]
    assert second[1:] == ["/printto:default=yes;showui=no", "Duplex", "score.pdf"]


def test_prepare_native_print_pdf_can_rotate_full_document(tmp_path: Path) -> None:
    from xw_office.services.printing.pdf_backends import _prepare_native_print_pdf

    pdf = tmp_path / "landscape.pdf"
    source = fitz.open()
    source.new_page(width=595, height=420)
    source.new_page(width=595, height=420)
    source.save(pdf)
    source.close()

    prepared = _prepare_native_print_pdf(str(pdf), None, rotate_degrees=90)

    try:
        assert prepared.path != str(pdf)
        rotated = fitz.open(prepared.path)
        try:
            assert rotated.page_count == 2
            assert [page.rotation for page in rotated] == [90, 90]
        finally:
            rotated.close()
    finally:
        Path(prepared.path).unlink(missing_ok=True)


def test_prepare_native_print_pdf_normalizes_small_pages_to_a5_without_distortion(
    tmp_path: Path,
) -> None:
    from xw_office.services.printing.pdf_backends import _prepare_native_print_pdf

    mm_to_pt = 72.0 / 25.4
    pdf = tmp_path / "mixed-a5.pdf"
    source = fitz.open()
    exact = source.new_page(width=210 * mm_to_pt, height=148 * mm_to_pt)
    exact.insert_text((20, 30), "Exact A5")
    small = source.new_page(width=203 * mm_to_pt, height=141 * mm_to_pt)
    small.insert_text((20, 30), "Small A5")
    source.save(pdf)
    source.close()

    prepared = _prepare_native_print_pdf(
        str(pdf),
        None,
        rotate_degrees=90,
        normalize_page_size="A5",
        max_upscale_percent=105,
    )

    try:
        normalized = fitz.open(prepared.path)
        try:
            assert normalized.page_count == 2
            assert [page.rotation for page in normalized] == [90, 90]
            assert normalized[0].rect.width == pytest.approx(148 * mm_to_pt, abs=0.02)
            assert normalized[0].rect.height == pytest.approx(210 * mm_to_pt, abs=0.02)
            assert normalized[1].rect.width == pytest.approx(148 * mm_to_pt, abs=0.02)
            assert normalized[1].rect.height == pytest.approx(210 * mm_to_pt, abs=0.02)
            assert "Exact A5" in normalized[0].get_text()
            assert "Small A5" in normalized[1].get_text()
        finally:
            normalized.close()
    finally:
        Path(prepared.path).unlink(missing_ok=True)


def test_pdf_xchange_without_spooler_confirmation_fails_closed(
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
    monkeypatch.setattr(
        "xw_office.services.printing.pdf_backends._WindowsSpoolerWatcher",
        lambda printer: _FakeSpoolerWatcher(printer, confirmed=False),
    )

    with pytest.raises(RuntimeError, match="keinen Druckauftrag"):
        NativePdfCliBackend(str(executable)).print(
            PdfPrintJob(
                pdf_path=str(pdf),
                printer_name="Noten A4 Duplex",
                backend="pdf_xchange",
                native_pdf_exe=str(executable),
            )
        )


def test_pdf_xchange_missing_executable_fails_without_fallback(tmp_path: Path) -> None:
    job = PdfPrintJob(
        pdf_path=str(tmp_path / "sample.pdf"),
        printer_name="Printer",
        backend="pdf_xchange",
        native_pdf_exe=str(tmp_path / "missing.exe"),
    )
    Path(job.pdf_path).write_bytes(b"%PDF-test")

    with pytest.raises(RuntimeError, match="EXE wurde nicht gefunden"):
        backend_for_job(job).print(job)


def test_pdf_xchange_nonzero_exit_fails_without_fallback(
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
    monkeypatch.setattr("xw_office.services.printing.pdf_backends._WindowsSpoolerWatcher", _FakeSpoolerWatcher)

    with pytest.raises(RuntimeError, match="Exit-Code 5"):
        NativePdfCliBackend(str(executable)).print(
            PdfPrintJob(
                pdf_path=str(pdf),
                printer_name="Printer",
                backend="pdf_xchange",
                native_pdf_exe=str(executable),
            )
        )
