"""Direct PDF printing via configured print plans and printer profiles."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtPrintSupport import QPrinter

from xw_studio.core.config import PrintingSection, PrintProfile
from xw_studio.services.printing.pdf_renderer import print_pdf

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
    dpi: int
    duplex: str


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
                    dpi=max(int(resolved.dpi or 600), 1),
                    duplex=str(resolved.duplex or "").strip(),
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
            dpi=max(int(resolved.dpi or 600), 1),
            duplex=str(resolved.duplex or "").strip(),
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
) -> None:
    """Print a PDF directly to configured printer targets without a dialog."""
    targets = resolve_plan_targets(printing, print_plan=print_plan, profile_id=profile_id)
    if not targets:
        raise RuntimeError("Kein Druckplan oder Profil fuer Produktdruck konfiguriert")

    effective_copies = max(int(copies or 1), 1)
    for _copy_index in range(effective_copies):
        for target in targets:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setPrinterName(target.printer_name)
            pages = None
            if page_count is not None:
                pages = page_indices_from_range_text(target.range_text, page_count=page_count)
            print_pdf(pdf_path, printer, dpi=target.dpi, pages=pages, duplex=target.duplex)


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
    if value == "END":
        return page_count
    if value.isdigit():
        return int(value)
    raise RuntimeError(f"Ungueltiger Seitenbereich: {token}")
