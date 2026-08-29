"""Direct PDF printing via configured print plans and printer profiles."""
from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from xw_office.core.config import PrintingSection, PrintProfile
from xw_office.services.printing.print_jobs import (
    BlackEnhancement,
    PdfBackendName,
    PdfPrintJob,
    PlacementMode,
    PrintJobKind,
    RenderColorMode,
)
from xw_office.services.printing.print_queue import PrintQueueService, global_print_queue

_ALL_RANGE_TOKENS = {"", "ALL", "ALLE", "ALLESEITEN", "*"}
_PROFILE_ALIASES = {
    "noten_a4_simplex": "noten_simplex",
    "noten_a4_duplex": "noten_duplex",
    "canon_brochure_mono": "brochure_mono",
    "canon_brochure_duo": "brochure_duo",
}


class PrintPlanPartialFailure(RuntimeError):
    """Raised when a multi-copy plan fails partway through a set.

    ``completed_copies`` counts full sets (every plan row printed once) that
    the print queue confirmed before the failing row, so callers can credit
    stock for what was actually produced instead of losing the count.
    """

    def __init__(self, message: str, *, completed_copies: int, job_ids: list[str]) -> None:
        super().__init__(message)
        self.completed_copies = completed_copies
        self.job_ids = job_ids


@dataclass(frozen=True)
class PlanTarget:
    range_text: str
    printer_name: str
    dpi: int | None
    placement_mode: PlacementMode
    page_size: str
    orientation: str
    scale_mode: str
    alignment: str
    x_offset_mm: float
    y_offset_mm: float
    rotate_degrees: int
    render_color_mode: RenderColorMode
    black_enhancement: BlackEnhancement
    black_threshold: int
    backend: PdfBackendName
    native_pdf_exe: str


def page_indices_from_range_text(range_text: str, *, page_count: int) -> list[int] | None:
    """Translate legacy-style page range syntax to 0-based page indices."""
    if page_count <= 0:
        return None
    compact = str(range_text or "").strip().upper().replace(" ", "")
    compact = compact.replace("ENDE", "END")
    if compact in _ALL_RANGE_TOKENS:
        return None

    seen: set[int] = set()
    result: list[int] = []
    for part in compact.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            start = _range_bound(left, page_count, default=1)
            end = _range_bound(right, page_count, default=page_count)
            if start > end:
                start, end = end, start
            numbers = range(start, end + 1)
        else:
            page_no = _range_bound(token, page_count, default=1)
            numbers = range(page_no, page_no + 1)
        for page_no in numbers:
            if page_no < 1 or page_no > page_count:
                raise RuntimeError(f"Seitenbereich ausserhalb des Dokuments: {range_text}")
            index = page_no - 1
            if index in seen:
                continue
            seen.add(index)
            result.append(index)
    return result or None


def resolve_plan_targets(
    printing: PrintingSection,
    *,
    print_plan: list[dict[str, str]] | None = None,
    profile_id: str = "",
) -> list[PlanTarget]:
    """Resolve configured plan/profile entries to concrete printer targets."""
    targets: list[PlanTarget] = []
    plan = list(print_plan or [])
    if plan:
        for entry in plan:
            if not isinstance(entry, dict):
                continue
            resolved = _resolve_profile(printing, str(entry.get("profile_id") or "").strip())
            if resolved is None or not resolved.printer_name.strip():
                raise RuntimeError("Ungueltiger Druckplan: Profil/Drucker fehlt")
            targets.append(
                PlanTarget(
                    range_text=str(entry.get("range") or "").strip() or "Alle Seiten",
                    printer_name=resolved.printer_name.strip(),
                    dpi=int(resolved.dpi) if resolved.dpi else None,
                    placement_mode=_placement_mode(resolved.placement_mode),
                    page_size=str(resolved.page_size or "").strip(),
                    orientation=str(resolved.orientation or "").strip(),
                    scale_mode=_scale_mode(resolved.scale_mode),
                    alignment=_alignment(resolved.alignment),
                    x_offset_mm=float(resolved.x_offset_mm),
                    y_offset_mm=float(resolved.y_offset_mm),
                    rotate_degrees=_rotate_degrees(resolved.rotate_degrees),
                    render_color_mode=_render_color_mode(resolved.render_color_mode),
                    black_enhancement=_black_enhancement(resolved.black_enhancement),
                    black_threshold=int(resolved.black_threshold),
                    backend=_backend_name(resolved.backend),
                    native_pdf_exe=str(resolved.native_pdf_exe or "").strip(),
                )
            )
        if targets:
            return targets

    resolved = _resolve_profile(printing, profile_id)
    if resolved is None or not resolved.printer_name.strip():
        return []
    return [
        PlanTarget(
            range_text="Alle Seiten",
            printer_name=resolved.printer_name.strip(),
            dpi=int(resolved.dpi) if resolved.dpi else None,
            placement_mode=_placement_mode(resolved.placement_mode),
            page_size=str(resolved.page_size or "").strip(),
            orientation=str(resolved.orientation or "").strip(),
            scale_mode=_scale_mode(resolved.scale_mode),
            alignment=_alignment(resolved.alignment),
            x_offset_mm=float(resolved.x_offset_mm),
            y_offset_mm=float(resolved.y_offset_mm),
            rotate_degrees=_rotate_degrees(resolved.rotate_degrees),
            render_color_mode=_render_color_mode(resolved.render_color_mode),
            black_enhancement=_black_enhancement(resolved.black_enhancement),
            black_threshold=int(resolved.black_threshold),
            backend=_backend_name(resolved.backend),
            native_pdf_exe=str(resolved.native_pdf_exe or "").strip(),
        )
    ]


def print_pdf_by_plan(
    pdf_path: str,
    printing: PrintingSection,
    *,
    print_plan: list[dict[str, str]] | None = None,
    profile_id: str = "",
    copies: int = 1,
    page_count: int | None = None,
    print_queue: PrintQueueService | None = None,
    job_kind: str = "product",
    wait: bool = False,
) -> list[str]:
    """Queue PDF print jobs for configured printer targets without a dialog.

    Jobs are dispatched copy-by-copy across all plan rows (one full set, then
    the next), not row-by-row with all copies at once. A multi-row plan (e.g.
    cover + body + insert) therefore comes off the printers as complete,
    ready-to-collate sets instead of one block per row.
    """
    targets = resolve_plan_targets(printing, print_plan=print_plan, profile_id=profile_id)
    if not targets:
        raise RuntimeError("Kein Druckplan oder Profil fuer Produktdruck konfiguriert")

    effective_copies = max(int(copies or 1), 1)
    queue = print_queue or global_print_queue()
    effective_kind = cast(
        PrintJobKind,
        "product" if job_kind not in {"music", "product", "invoice", "label"} else job_kind,
    )
    job_ids: list[str] = []
    completed_copies = 0
    for _copy_index in range(effective_copies):
        for target in targets:
            pages = None
            if page_count is not None:
                pages = page_indices_from_range_text(target.range_text, page_count=page_count)
            job = PdfPrintJob(
                pdf_path=pdf_path,
                printer_name=target.printer_name,
                pages=pages,
                copies=1,
                dpi=target.dpi,
                job_kind=effective_kind,
                description=f"{job_kind}: {pdf_path}",
                placement_mode=target.placement_mode,
                page_size=target.page_size,  # type: ignore[arg-type]
                orientation=target.orientation,  # type: ignore[arg-type]
                scale_mode=target.scale_mode,  # type: ignore[arg-type]
                alignment=target.alignment,  # type: ignore[arg-type]
                x_offset_mm=target.x_offset_mm,
                y_offset_mm=target.y_offset_mm,
                rotate_degrees=target.rotate_degrees,
                render_color_mode=target.render_color_mode,
                black_enhancement=target.black_enhancement,
                black_threshold=target.black_threshold,
                backend=target.backend,
                native_pdf_exe=target.native_pdf_exe,
            )
            if wait:
                result = queue.enqueue_and_wait(job)
                if not result.success:
                    raise PrintPlanPartialFailure(
                        result.message or f"Druck fehlgeschlagen: {target.printer_name}",
                        completed_copies=completed_copies,
                        job_ids=job_ids,
                    )
            else:
                queue.enqueue(job)
            job_ids.append(job.id)
        completed_copies += 1
    return job_ids


def _resolve_profile(printing: PrintingSection, profile_id: str) -> PrintProfile | None:
    requested = str(profile_id or "").strip()
    if not requested:
        return None
    direct = printing.resolve_profile(requested)
    if direct is not None:
        return direct
    alias = _PROFILE_ALIASES.get(requested.casefold())
    if alias:
        aliased = printing.resolve_profile(alias)
        if aliased is not None:
            return aliased
    return None


def _range_bound(token: str, page_count: int, *, default: int) -> int:
    value = str(token or "").strip().upper()
    if not value:
        return default
    if value == "START":
        return 1
    if value == "END":
        return page_count
    if value.isdigit():
        return int(value)
    raise RuntimeError(f"Ungueltiger Seitenbereich: {token}")


def _placement_mode(value: str) -> PlacementMode:
    normalized = str(value or "paper_origin").strip().casefold()
    if normalized in {"paper_origin", "printable_origin", "calibrated"}:
        return cast(PlacementMode, normalized)
    return "paper_origin"


def _scale_mode(value: str) -> str:
    normalized = str(value or "none").strip().casefold()
    if normalized in {"none", "fit"}:
        return normalized
    return "none"


def _backend_name(value: str) -> PdfBackendName:
    normalized = str(value or "qt_raster").strip().casefold()
    if normalized in {"qt", "qt_raster", "internal"}:
        return "qt_raster"
    if normalized in {"pdf_xchange", "pdf-xchange", "native_pdf_cli"}:
        return "pdf_xchange"
    raise RuntimeError(f"Unbekanntes PDF-Druckbackend im Profil: {value}")


def _alignment(value: str) -> str:
    normalized = str(value or "top_left").strip().casefold()
    if normalized in {"top_left", "center"}:
        return normalized
    return "top_left"


def _rotate_degrees(value: int) -> int:
    normalized = int(value or 0) % 360
    if normalized in {0, 90, 180, 270}:
        return normalized
    raise RuntimeError(f"Ungueltige PDF-Drehung im Profil: {value}")


def _render_color_mode(value: str) -> RenderColorMode:
    normalized = str(value or "auto").strip().casefold()
    if normalized in {"auto", "rgb", "gray"}:
        return cast(RenderColorMode, normalized)
    return "auto"


def _black_enhancement(value: str) -> BlackEnhancement:
    normalized = str(value or "auto").strip().casefold()
    if normalized in {
        "auto",
        "none",
        "darken",
        "mild_darken",
        "adaptive_music",
        "auto_music",
        "music_black",
        "threshold",
    }:
        return cast(BlackEnhancement, normalized)
    return "auto"
