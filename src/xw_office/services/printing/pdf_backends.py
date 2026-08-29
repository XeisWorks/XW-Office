"""Pluggable PDF print backends used by the sequential print queue."""
from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import Any

from xw_office.services.printing.pdf_renderer import print_pdf_with_qprinter
from xw_office.services.printing.print_jobs import PdfPrintJob

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
            scale_percent=job.scale_percent,
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

        prepared_pdf = _prepare_native_print_pdf(
            str(pdf_path),
            job.pages,
            rotate_degrees=job.rotate_degrees,
            normalize_page_size=job.normalize_page_size,
            max_upscale_percent=job.max_upscale_percent,
        )

        try:
            if not self._executable_path or not executable.is_file():
                raise RuntimeError(
                    "PDF-XChange Editor wurde fuer dieses Druckprofil konfiguriert, "
                    f"aber die EXE wurde nicht gefunden: {self._executable_path or '(kein Pfad)'}"
                )
            self._print_with_pdf_xchange(job, str(executable), prepared_pdf.path)
        finally:
            prepared_pdf.schedule_cleanup()

    def _print_with_pdf_xchange(self, job: PdfPrintJob, executable: str, pdf_path: str) -> None:
        command = _pdf_xchange_print_command(executable, job.printer_name, pdf_path)
        command_line = subprocess.list2cmdline(command)
        copies = max(int(job.copies), 1)
        for copy_number in range(copies):
            with _WindowsSpoolerWatcher(job.printer_name) as spooler:
                logger.info(
                    "Native PDF print dispatch: backend=pdf_xchange_printto printer='%s' copy=%s/%s command=%s",
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
                spooler_confirmed = spooler.wait(timeout_seconds=10.0)
            if stdout or stderr:
                logger.info(
                    "Native PDF print process output: printer='%s' stdout=%r stderr=%r",
                    job.printer_name,
                    stdout,
                    stderr,
                )
            if not spooler_confirmed:
                raise RuntimeError(
                    "PDF-XChange hat keinen Druckauftrag an den Windows-Spooler des "
                    f"Druckers '{job.printer_name}' uebergeben. Der Auftrag wurde abgebrochen; "
                    "es erfolgt keine Bestandsbuchung."
                )
            logger.info(
                "Native PDF print confirmed by spooler: backend=pdf_xchange_printto printer='%s' copy=%s/%s",
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
    """Build PDF-XChange's dedicated silent print-to command.

    The printer is a separate argument, so spaces and non-ASCII characters are
    quoted by Windows without becoming part of PDF-XChange's option parser.
    Every invocation therefore carries its own explicit target printer.
    """
    return [executable, "/printto:default=yes;showui=no", printer_name, pdf_path]


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


def _prepare_native_print_pdf(
    pdf_path: str,
    pages: list[int] | None,
    *,
    rotate_degrees: int = 0,
    normalize_page_size: str = "",
    max_upscale_percent: float = 100.0,
) -> _PreparedNativePdf:
    normalized_rotation = int(rotate_degrees or 0) % 360
    if normalized_rotation not in {0, 90, 180, 270}:
        raise RuntimeError(f"Ungueltige PDF-Drehung im Profil: {rotate_degrees}")
    normalized_page_size = str(normalize_page_size or "").strip().upper()
    if pages is None and normalized_rotation == 0 and not normalized_page_size:
        return _PreparedNativePdf(path=str(pdf_path), cleanup=False)
    temp_path = _extract_pdf_pages(
        pdf_path,
        pages,
        rotate_degrees=normalized_rotation,
        normalize_page_size=normalized_page_size,
        max_upscale_percent=max_upscale_percent,
    )
    if not temp_path or temp_path == str(pdf_path):
        return _PreparedNativePdf(path=str(pdf_path), cleanup=False)
    return _PreparedNativePdf(path=temp_path, cleanup=True)


def _extract_pdf_pages(
    pdf_path: str,
    pages: list[int] | None,
    *,
    rotate_degrees: int = 0,
    normalize_page_size: str = "",
    max_upscale_percent: float = 100.0,
) -> str:
    page_indices = None if pages is None else sorted({int(page) for page in pages if int(page) >= 0})
    if page_indices == []:
        return str(pdf_path)
    try:
        import fitz  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Seitenauswahl fuer nativen PDF-Druck erfordert PyMuPDF/fitz") from exc
    source = fitz.open(str(pdf_path))
    target = fitz.open()
    try:
        max_page = source.page_count - 1
        selected_indices = range(source.page_count) if page_indices is None else page_indices
        for page_index in selected_indices:
            if page_index <= max_page:
                source_page = source[page_index]
                target_size = _normalized_page_dimensions(
                    normalize_page_size,
                    source_page.rect.width,
                    source_page.rect.height,
                )
                if target_size is None or _same_page_size(source_page.rect, target_size):
                    target.insert_pdf(source, from_page=page_index, to_page=page_index)
                else:
                    width, height = target_size
                    target_page = target.new_page(width=width, height=height)
                    scale = min(width / source_page.rect.width, height / source_page.rect.height)
                    scale = min(scale, max(float(max_upscale_percent), 100.0) / 100.0)
                    fitted_width = source_page.rect.width * scale
                    fitted_height = source_page.rect.height * scale
                    left = (width - fitted_width) / 2.0
                    top = (height - fitted_height) / 2.0
                    target_page.show_pdf_page(
                        fitz.Rect(left, top, left + fitted_width, top + fitted_height),
                        source,
                        page_index,
                        keep_proportion=True,
                    )
                if rotate_degrees:
                    page = target[target.page_count - 1]
                    page.set_rotation((int(page.rotation or 0) + rotate_degrees) % 360)
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


def _normalized_page_dimensions(
    page_size: str,
    source_width: float,
    source_height: float,
) -> tuple[float, float] | None:
    normalized = str(page_size or "").strip().upper()
    if not normalized:
        return None
    if normalized != "A5":
        raise RuntimeError(f"Nicht unterstuetztes natives PDF-Seitenformat: {page_size}")
    a5_short = 148.0 * 72.0 / 25.4
    a5_long = 210.0 * 72.0 / 25.4
    if source_width >= source_height:
        return a5_long, a5_short
    return a5_short, a5_long


def _same_page_size(rect: Any, target_size: tuple[float, float]) -> bool:
    tolerance = 0.5 * 72.0 / 25.4
    return abs(float(rect.width) - target_size[0]) <= tolerance and abs(
        float(rect.height) - target_size[1]
    ) <= tolerance


class _WindowsSpoolerWatcher:
    """Observe a new job on one printer without spawning PowerShell polls."""

    def __init__(self, printer_name: str) -> None:
        self._printer_name = str(printer_name or "").strip()
        self._win32print: Any = None
        self._winspool: Any = None
        self._kernel32: Any = None
        self._printer_handle: Any = None
        self._notification_handle: Any = None
        try:
            import win32print  # type: ignore[import-untyped]
            import ctypes
            from ctypes import wintypes

            self._win32print = win32print
            self._printer_handle = win32print.OpenPrinter(self._printer_name)
            self._winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            find_first = self._winspool.FindFirstPrinterChangeNotification
            find_first.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
            find_first.restype = wintypes.HANDLE
            self._notification_handle = find_first(
                int(self._printer_handle),
                0x00000100,  # PRINTER_CHANGE_ADD_JOB
                0,
                None,
            )
            if not self._notification_handle or int(self._notification_handle) == -1:
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception as exc:  # noqa: BLE001 - converted to a user-facing print failure.
            self.close()
            raise RuntimeError(
                f"Windows-Spooler fuer Drucker '{self._printer_name}' konnte nicht ueberwacht werden: {exc}"
            ) from exc

    def __enter__(self) -> _WindowsSpoolerWatcher:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()

    def wait(self, *, timeout_seconds: float) -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            wait_for_single = self._kernel32.WaitForSingleObject
            wait_for_single.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            wait_for_single.restype = wintypes.DWORD
            result = wait_for_single(
                self._notification_handle,
                max(1, int(float(timeout_seconds) * 1000)),
            )
            if result == 0:  # WAIT_OBJECT_0
                return True
            if result == 0x00000102:  # WAIT_TIMEOUT
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Windows-Spooler-Bestaetigung fuer '{self._printer_name}' ist fehlgeschlagen: {exc}"
            ) from exc

    def close(self) -> None:
        notification = self._notification_handle
        self._notification_handle = None
        if notification is not None:
            try:
                self._winspool.FindClosePrinterChangeNotification(notification)
            except Exception:
                pass
        printer = self._printer_handle
        self._printer_handle = None
        if printer is not None:
            try:
                self._win32print.ClosePrinter(printer)
            except Exception:
                pass
