"""Pluggable PDF print backends used by the sequential print queue."""
from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from pathlib import Path
import subprocess

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

        # Keep the printer value unquoted inside the option. ``subprocess`` wraps
        # the complete option argument when the name contains spaces. Embedded
        # quotes would be escaped as \" on Windows and PDF-XChange V11 silently
        # ignores the resulting printer option. The documented /print command is
        # intentionally dispatched only once per requested copy: Editor V11 may
        # return before the Windows spooler starts the physical output, so a
        # missing immediately-visible queue entry must never trigger a retry.
        options = ["default=yes", "showui=no", f"printer={job.printer_name}"]
        pages = _pdf_xchange_page_range(job.pages)
        if pages:
            options.append(f"pages={pages}")
        command = [str(executable), f"/print:{';'.join(options)}", str(pdf_path)]

        # PDF-XChange's /print switch has no copies parameter. Repeating the
        # documented silent command keeps the configured driver profile intact.
        for copy_number in range(max(int(job.copies), 1)):
            logger.info(
                "Native PDF print dispatch: backend=pdf_xchange printer='%s' copy=%s/%s",
                job.printer_name,
                copy_number + 1,
                max(int(job.copies), 1),
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
