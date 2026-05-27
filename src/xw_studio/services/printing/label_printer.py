"""Legacy-compatible Brother bPAC label printer."""
from __future__ import annotations

from pathlib import Path

from xw_studio.core.config import PrintingSection
from xw_studio.services.printing.print_jobs import BrotherLbxLabelJob
from xw_studio.services.printing.print_queue import PrintQueueService, global_print_queue


class LabelPrinter:
    """Equivalent behavior to old app LabelPrinter (LBX + object 'Empfaenger')."""

    def __init__(self, printing: PrintingSection, print_queue: PrintQueueService | None = None) -> None:
        self._printing = printing
        self._print_queue = print_queue

    def _printer_name(self) -> str:
        profile = self._printing.resolve_profile("label")
        if profile is not None and profile.printer_name.strip():
            return profile.printer_name.strip()
        explicit = str(self._printing.label_printer or "").strip()
        if explicit:
            return explicit
        names = [str(name).strip() for name in self._printing.configured_printer_names if str(name).strip()]
        if len(names) > 1:
            return names[1]
        return names[0] if names else ""

    def _template_path(self, override: str | None = None) -> str:
        candidate = str(override or self._printing.label_template_path or "").strip()
        if not candidate:
            raise RuntimeError("Etikettenvorlage fehlt")
        path = Path(candidate)
        if not path.is_absolute():
            root = Path(__file__).resolve().parents[4]
            path = (root / path).resolve()
        if not path.exists():
            raise RuntimeError("Etikettenvorlage fehlt")
        return str(path)

    def print_address(
        self,
        lines: list[str],
        *,
        template_path: str | None = None,
        overlay_object: str | None = None,
        overlay_text: str | None = None,
    ) -> None:
        printer_name = self._printer_name()
        if not printer_name:
            raise RuntimeError("Kein Etikettendrucker konfiguriert")
        template = self._template_path(template_path)
        queue = self._print_queue or global_print_queue()
        queue.enqueue(
            BrotherLbxLabelJob(
                printer_name=printer_name,
                template_path=template,
                lines=[str(line) for line in lines],
                overlay_object=overlay_object,
                overlay_text=overlay_text,
                description="Address Label",
            )
        )
