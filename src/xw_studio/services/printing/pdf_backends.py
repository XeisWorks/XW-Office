"""Pluggable PDF print backends used by the sequential print queue."""
from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import threading
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
        pdf_path = Path(job.pdf_path)
        if not pdf_path.is_file():
            raise RuntimeError(f"Produkt-PDF wurde nicht gefunden: {pdf_path}")

        prepared_pdf = _prepare_native_print_pdf(str(pdf_path), job.pages)

        try:
            if not self._executable_path or not executable.is_file():
                raise RuntimeError(
                    "PDF-XChange Editor wurde fuer dieses Druckprofil konfiguriert, "
                    f"aber die EXE wurde nicht gefunden: {self._executable_path or '(kein Pfad)'}"
                )
            self._print_with_pdf_xchange(job, str(executable), prepared_pdf.path)
            return
        except Exception as exc:  # noqa: BLE001 - Acrobat is the explicit fallback.
            logger.warning(
                "PDF-XChange native print failed; trying Acrobat fallback: printer='%s' file='%s' error=%s",
                job.printer_name,
                prepared_pdf.path,
                exc,
            )
            _print_with_acrobat_fallback(job, prepared_pdf.path, timeout_seconds=self._timeout_seconds)
        finally:
            prepared_pdf.schedule_cleanup()

    def _print_with_pdf_xchange(self, job: PdfPrintJob, executable: str, pdf_path: str) -> None:
        command = _pdf_xchange_print_command(executable, job.printer_name, pdf_path)
        command_line = subprocess.list2cmdline(command)
        copies = max(int(job.copies), 1)
        for copy_number in range(copies):
            spooler_before = _windows_print_job_snapshot(job.printer_name)
            logger.info(
                "Native PDF print dispatch: backend=pdf_xchange_print printer='%s' copy=%s/%s command=%s",
                job.printer_name,
                copy_number + 1,
                copies,
                command_line,
            )
            completed = _run_print_command(command, timeout_seconds=self._timeout_seconds)
            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            if completed.returncode != 0:
                detail = (stderr or stdout).strip()
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(
                    f"PDF-XChange Druckaufruf fehlgeschlagen (Exit-Code {completed.returncode}){suffix}"
                )
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
                logger.info(
                    "Native PDF print handed to PDF-XChange; no spooler job was visible in the diagnostic window "
                    "for printer='%s'. This can be normal when the driver accepts the job immediately. command=%s",
                    job.printer_name,
                    command_line,
                )
            logger.info(
                "Native PDF print accepted: backend=pdf_xchange_print printer='%s' copy=%s/%s",
                job.printer_name,
                copy_number + 1,
                copies,
            )


def backend_for_job(job: PdfPrintJob) -> PdfPrintBackend:
    """Resolve the explicitly selected backend without quality-reducing fallback."""
    if job.backend == "qt_raster":
        return QtRasterBackend()
    if job.backend == "pdf_xchange":
        return NativePdfCliBackend(job.native_pdf_exe)
    raise RuntimeError(f"Unbekanntes PDF-Druckbackend: {job.backend}")


def _pdf_xchange_print_command(
    executable: str,
    printer_name: str,
    pdf_path: str,
) -> list[str]:
    """Build an explicit, silent PDF-XChange print command.

    ``/printto`` can hand subsequent invocations to an already running editor
    instance, where the first printer selection may remain active.  PDF-XChange's
    documented ``/print`` command accepts the target printer as part of each
    invocation.  ``default=yes`` also prevents settings from a previous editor
    print operation from leaking into the job, while ``showui=no`` keeps the
    editor and print dialog hidden.

    Page-restricted print plans are converted to temporary PDFs before this
    command is built.
    """
    options = f'/print:default=yes;showui=no;printer="{printer_name}"'
    return [executable, options, pdf_path]


def _run_print_command(command: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - executables are explicit print backend config.
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Druckaufruf hat nach {timeout_seconds:.0f} Sekunden nicht geantwortet") from exc
    except OSError as exc:
        raise RuntimeError(f"Druckprogramm konnte nicht gestartet werden: {exc}") from exc


class _PreparedNativePdf:
    def __init__(self, *, path: str, cleanup: bool) -> None:
        self.path = path
        self._cleanup = cleanup

    def schedule_cleanup(self) -> None:
        if not self._cleanup:
            return
        path = self.path

        def cleanup() -> None:
            try:
                os.remove(path)
            except OSError:
                pass

        timer = threading.Timer(180.0, cleanup)
        timer.daemon = True
        timer.start()


def _prepare_native_print_pdf(pdf_path: str, pages: list[int] | None) -> _PreparedNativePdf:
    if pages is None:
        return _PreparedNativePdf(path=str(pdf_path), cleanup=False)
    temp_path = _extract_pdf_pages(pdf_path, pages)
    if not temp_path or temp_path == str(pdf_path):
        return _PreparedNativePdf(path=str(pdf_path), cleanup=False)
    return _PreparedNativePdf(path=temp_path, cleanup=True)


def _extract_pdf_pages(pdf_path: str, pages: list[int]) -> str:
    page_indices = sorted({int(page) for page in pages if int(page) >= 0})
    if not page_indices:
        return str(pdf_path)
    try:
        import fitz  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Seitenauswahl fuer nativen PDF-Druck erfordert PyMuPDF/fitz") from exc
    source = fitz.open(str(pdf_path))
    target = fitz.open()
    try:
        max_page = source.page_count - 1
        for page_index in page_indices:
            if page_index <= max_page:
                target.insert_pdf(source, from_page=page_index, to_page=page_index)
        if target.page_count == 0:
            raise RuntimeError("Seitenauswahl enthaelt keine gueltigen PDF-Seiten")
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="xw_print_pages_")
        temp_path = handle.name
        handle.close()
        target.save(temp_path)
        return temp_path
    finally:
        target.close()
        source.close()


def _print_with_acrobat_fallback(job: PdfPrintJob, pdf_path: str, *, timeout_seconds: float) -> None:
    executable = _acrobat_executable()
    if not executable:
        raise RuntimeError(
            "PDF-XChange konnte nicht drucken und Acrobat wurde nicht gefunden."
        )
    printer_info = _windows_printer_driver_port(job.printer_name)
    command = [executable, "/t", pdf_path, job.printer_name]
    if printer_info.get("driver"):
        command.append(printer_info["driver"])
    if printer_info.get("port"):
        command.append(printer_info["port"])
    copies = max(int(job.copies), 1)
    for copy_number in range(copies):
        logger.info(
            "Native PDF print fallback dispatch: backend=acrobat_t printer='%s' copy=%s/%s command=%s",
            job.printer_name,
            copy_number + 1,
            copies,
            subprocess.list2cmdline(command),
        )
        try:
            subprocess.Popen(  # noqa: S603 - Acrobat path is discovered from known install paths/env.
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise RuntimeError(f"Acrobat-Fallback konnte nicht gestartet werden: {exc}") from exc
        time.sleep(min(2.0, max(float(timeout_seconds), 0.1)))


def _acrobat_executable() -> str:
    candidates = [
        os.getenv("XW_STUDIO_ACROBAT_EXE", ""),
        r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
        r"C:\Program Files (x86)\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
        r"C:\Program Files\Adobe\Acrobat 2020\Acrobat\Acrobat.exe",
        r"C:\Program Files (x86)\Adobe\Acrobat 2020\Acrobat\Acrobat.exe",
        r"C:\Program Files\Adobe\Acrobat 2017\Acrobat\Acrobat.exe",
        r"C:\Program Files (x86)\Adobe\Acrobat 2017\Acrobat\Acrobat.exe",
        r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
        r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
        r"C:\Program Files\Adobe\Reader\AcroRd32.exe",
        r"C:\Program Files (x86)\Adobe\Reader\AcroRd32.exe",
    ]
    for candidate in candidates:
        path = Path(str(candidate or "").strip())
        if path.is_file():
            return str(path)
    return ""


def _windows_printer_driver_port(printer_name: str) -> dict[str, str]:
    if os.name != "nt":
        return {}
    try:
        import win32print  # type: ignore[import-untyped]

        handle = win32print.OpenPrinter(str(printer_name or ""))
        try:
            info = win32print.GetPrinter(handle, 2)
        finally:
            win32print.ClosePrinter(handle)
        return {
            "driver": str(info.get("pDriverName") or "").strip(),
            "port": str(info.get("pPortName") or "").strip(),
        }
    except Exception as exc:  # noqa: BLE001 - Acrobat can still try with printer name only.
        logger.debug("Printer driver/port lookup failed for '%s': %s", printer_name, exc)
        return {}



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
