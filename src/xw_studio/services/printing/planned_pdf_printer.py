"""Direct PDF printing via configured print plans and printer profiles."""
from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from xw_studio.core.config import PrintingSection, PrintProfile
from xw_studio.services.printing.print_jobs import PdfPrintJob, PlacementMode, PrintJobKind
from xw_studio.services.printing.print_queue import PrintQueueService, global_print_queue

_ALL_RANGE_TOKENS = {"", "ALL", "ALLE", "ALLESEITEN", "*"}
_PROFILE_ALIASES = {
    "noten_a4_simplex": "noten_simplex",
    "noten_a4_duplex": "noten_duplex",
    "canon_brochure_mono": "brochure_mono",
    "canon_brochure_duo": "brochure_duo",
}


@dataclass(frozen=True)
class PlanTarget:
    range_text: str
    printer_name: str
    dpi: int | None
    placement_mode: PlacementMode
    x_offset_mm: float
    y_offset_mm: float


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
                    x_offset_mm=float(resolved.x_offset_mm),
                    y_offset_mm=float(resolved.y_offset_mm),
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
            x_offset_mm=float(resolved.x_offset_mm),
            y_offset_mm=float(resolved.y_offset_mm),
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
) -> None:
    """Queue PDF print jobs for configured printer targets without a dialog."""
    targets = resolve_plan_targets(printing, print_plan=print_plan, profile_id=profile_id)
    if not targets:
        raise RuntimeError("Kein Druckplan oder Profil fuer Produktdruck konfiguriert")

    effective_copies = max(int(copies or 1), 1)
    queue = print_queue or global_print_queue()
    effective_kind = cast(
        PrintJobKind,
        "product" if job_kind not in {"music", "product", "invoice", "label"} else job_kind,
    )
    for target in targets:
        pages = None
        if page_count is not None:
            pages = page_indices_from_range_text(target.range_text, page_count=page_count)
        queue.enqueue(
            PdfPrintJob(
                pdf_path=pdf_path,
                printer_name=target.printer_name,
                pages=pages,
                copies=effective_copies,
                dpi=target.dpi,
                job_kind=effective_kind,
                description=f"{job_kind}: {pdf_path}",
                placement_mode=target.placement_mode,
                x_offset_mm=target.x_offset_mm,
                y_offset_mm=target.y_offset_mm,
            )
        )


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
