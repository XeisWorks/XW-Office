"""Central printer status snapshot service."""
from __future__ import annotations

from dataclasses import dataclass

from xw_studio.core.config import AppConfig
from xw_studio.core.printer_detect import discover_printers_cached, evaluate_printer_status
from xw_studio.core.types import PrinterStatus


@dataclass(frozen=True)
class PrinterStatusSnapshot:
    status: PrinterStatus
    printing_allowed: bool
    color: str
    tooltip: str


class PrinterStatusService:
    """Provide one shared printer-status snapshot for the app."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._snapshot = PrinterStatusSnapshot(
            status=PrinterStatus.YELLOW,
            printing_allowed=False,
            color="yellow",
            tooltip="Druckerstatus wird geprüft...",
        )

    def snapshot(self) -> PrinterStatusSnapshot:
        return self._snapshot

    def refresh(self, *, force: bool = False) -> PrinterStatusSnapshot:
        names = list(self._config.printing.configured_printer_names)
        discovered = discover_printers_cached(ttl_seconds=0.0 if force else 60.0)
        status = evaluate_printer_status(discovered, names)
        self._snapshot = self._snapshot_for_status(status)
        return self._snapshot

    @staticmethod
    def _snapshot_for_status(status: PrinterStatus) -> PrinterStatusSnapshot:
        if status == PrinterStatus.GREEN:
            return PrinterStatusSnapshot(
                status=status,
                printing_allowed=True,
                color="green",
                tooltip="Drucker: bereit (Ampel gruen)",
            )
        if status == PrinterStatus.YELLOW:
            return PrinterStatusSnapshot(
                status=status,
                printing_allowed=True,
                color="yellow",
                tooltip="Drucker: teilweise (Ampel gelb)",
            )
        return PrinterStatusSnapshot(
            status=status,
            printing_allowed=False,
            color="red",
            tooltip="Drucker: nicht verfuegbar - Druck deaktiviert (Ampel rot)",
        )
