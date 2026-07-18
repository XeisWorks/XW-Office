"""Pluggable PDF print backends used by the sequential print queue."""
from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import os
from pathlib import Path
import subprocess
import time

from xw_studio.services.printing.pdf_renderer import print_pdf_with_qprinter
from xw_studio.services.printing.print_jobs import PdfPrintJob

logger = logging.getLogger(__name__)


class PdfPrintBackend(ABC):
    """Execute one PDF job or raise a user-facing exception on failure."""

    @abstractmethod
    def print(self, job: PdfPrintJob) -> None:
        """Dispatch *job* to its configured printer."""


class QtRasterBackend(PdfPrintBackend):
    """Existing robust PyMuPDF/QPrinter raster backend."""

    def print(self, job: PdfPrintJob) -> None:
        print_pdf_with_qprinter(
            job.pdf_path,
            job.printer_name,
            pages=job.pages,
            copies=job.copies,
            dpi=job.dpi,
            fallback_dpi=job.effective_dpi,
            placement_mode=job.placement_mode,
            page_size=job.page_size,
            orientation=job.orientation,
            scale_mode=job.scale_mode,
            alignment=job.alignment,
            x_offset_mm=job.x_offset_mm,
            y_offset_mm=job.y_offset_mm,
            job_kind=job.job_kind,
            render_color_mode=job.effective_render_color_mode,
            black_enhancement=job.effective_black_enhancement,
            black_threshold=job.black_threshold,
        )


class NativePdfCliBackend(PdfPrintBackend):
    """Native vector PDF printing through PDF-XChange Editor's documented CLI."""

    def __init__(self, executable_path: str, *, timeout_seconds: float = 120.0) -> None:
        self._executable_path = str(executable_path or "").strip()
        self._timeout_seconds = max(float(timeout_seconds), 1.0)

    def print(self, job: PdfPrintJob) -> None:
        executable = Path(self._executable_path)
        if not self._executable_path or not executable.is_file():
            raise RuntimeError(
                "PDF-XChange Editor wurde fuer dieses Druckprofil konfiguriert, "
                f"aber die EXE wurde nicht gefunden: {self._executable_path or '(kein Pfad)'}"
            )
        pdf_path = Path(job.pdf_path)
        if not pdf_path.is_file():
            raise RuntimeError(f"Produkt-PDF wurde nicht gefunden: {pdf_path}")

        # The PDF-XChange command line accepts printer names with spaces when
        # the value inside /print is quoted. Avoid default=yes here: Tracker
        # support notes that this can reuse/mix the Editor's last print state
        # and can prevent a target printer option from behaving predictably.
        options = ["showui=no", f'printer="{_pdf_xchange_escape_option_value(job.printer_name)}"']
        pages = _pdf_xchange_page_range(job.pages)
        if pages:
            options.append(f"pages={pages}")
        command = [str(executable), f"/print:{';'.join(options)}", str(pdf_path)]
        command_line = subprocess.list2cmdline(command)

        # PDF-XChange's /print switch has no copies parameter. Repeating the
        # documented silent command keeps the configured driver profile intact.
        for copy_number in range(max(int(job.copies), 1)):
            spooler_before = _windows_print_job_snapshot(job.printer_name)
            logger.info(
                "Native PDF print dispatch: backend=pdf_xchange printer='%s' copy=%s/%s command=%s",
                job.printer_name,
                copy_number + 1,
                max(int(job.copies), 1),
                command_line,
            )
            try:
                completed = subprocess.run(  # noqa: S603 - executable is explicit profile config
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"PDF-XChange Druckaufruf hat nach {self._timeout_seconds:.0f} Sekunden nicht geantwortet"
                ) from exc
            except OSError as exc:
                raise RuntimeError(f"PDF-XChange konnte nicht gestartet werden: {exc}") from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(
                    f"PDF-XChange Druckaufruf fehlgeschlagen (Exit-Code {completed.returncode}){suffix}"
                )
            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            if stdout or stderr:
                logger.info(
                    "Native PDF print process output: printer='%s' stdout=%r stderr=%r",
                    job.printer_name,
                    stdout,
                    stderr,
                )
            spooler_after = _wait_for_spooler_change(job.printer_name, previous_snapshot=spooler_before)
            if spooler_after:
                logger.info(
                    "Native PDF print spooler observed: printer='%s' jobs=%s",
                    job.printer_name,
                    spooler_after,
                )
            else:
                logger.warning(
                    "Native PDF print was accepted by PDF-XChange but no Windows spooler job was observed "
                    "for printer='%s' within the diagnostic window. command=%s",
                    job.printer_name,
                    command_line,
                )
            logger.info(
                "Native PDF print accepted asynchronously: printer='%s' copy=%s/%s",
                job.printer_name,
                copy_number + 1,
                max(int(job.copies), 1),
            )


def backend_for_job(job: PdfPrintJob) -> PdfPrintBackend:
    """Resolve the explicitly selected backend without quality-reducing fallback."""
    if job.backend == "qt_raster":
        return QtRasterBackend()
    if job.backend == "pdf_xchange":
        return NativePdfCliBackend(job.native_pdf_exe)
    raise RuntimeError(f"Unbekanntes PDF-Druckbackend: {job.backend}")


def _pdf_xchange_page_range(pages: list[int] | None) -> str:
    """Convert zero-based page indices to a compact PDF-XChange range."""
    if pages is None:
        return ""
    numbers = sorted({int(page) + 1 for page in pages if int(page) >= 0})
    if not numbers:
        return ""
    ranges: list[str] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def _pdf_xchange_escape_option_value(value: str) -> str:
    """Escape one quoted PDF-XChange /print option value."""
    return str(value or "").replace('"', '\\"')


def _windows_print_job_snapshot(printer_name: str) -> str:
    """Return a compact active Windows spooler snapshot for diagnostics."""
    if os.name != "nt":
        return ""
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "$p=$env:XW_PRINT_DIAG_PRINTER; "
            "Get-PrintJob -PrinterName $p -ErrorAction SilentlyContinue | "
            "Select-Object ID,DocumentName,JobStatus | ConvertTo-Json -Compress"
        ),
    ]
    env = dict(os.environ)
    env["XW_PRINT_DIAG_PRINTER"] = str(printer_name or "")
    try:
        completed = subprocess.run(  # noqa: S603 - PowerShell is used for Windows print diagnostics.
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must not break printing.
        logger.debug("Windows spooler diagnostic failed for printer='%s': %s", printer_name, exc)
        return ""
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if detail:
            logger.debug("Windows spooler diagnostic returned %s: %s", completed.returncode, detail)
        return ""
    return (completed.stdout or "").strip()


def _wait_for_spooler_change(printer_name: str, *, previous_snapshot: str) -> str:
    """Poll briefly for a visible spooler entry after PDF-XChange returns."""
    deadline = time.monotonic() + 8.0
    latest = ""
    while time.monotonic() < deadline:
        latest = _windows_print_job_snapshot(printer_name)
        if latest and latest != previous_snapshot:
            return latest
        time.sleep(0.4)
    return latest if latest and latest != previous_snapshot else ""
