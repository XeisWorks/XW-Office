"""Printer discovery and traffic-light status for multi-PC support."""
from __future__ import annotations

import logging
from dataclasses import dataclass
import time

from xw_studio.core.types import PrinterStatus

logger = logging.getLogger(__name__)

_PRINTER_CACHE_TTL_SECONDS = 60.0
_PRINTER_CACHE: tuple[float, list[PrinterInfo]] | None = None


@dataclass
class PrinterInfo:
    name: str
    is_default: bool = False
    is_network: bool = False


def discover_printers() -> list[PrinterInfo]:
    """List available printers on this machine."""
    try:
        import win32print  # type: ignore[import-untyped]
        printers = []
        default_name = win32print.GetDefaultPrinter()
        for flags, _desc, name, _comment in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        ):
            printers.append(PrinterInfo(
                name=name,
                is_default=(name == default_name),
                is_network=bool(flags & win32print.PRINTER_ENUM_CONNECTIONS),
            ))
        return printers
    except ImportError:
        logger.warning("pywin32 not available — printer detection disabled")
        return []
    except Exception as exc:
        logger.error("Printer discovery failed: %s", exc)
        return []


def discover_printers_cached(*, ttl_seconds: float = _PRINTER_CACHE_TTL_SECONDS) -> list[PrinterInfo]:
    """Return cached printer discovery results for a short TTL."""
    global _PRINTER_CACHE
    now = time.monotonic()
    if _PRINTER_CACHE is not None:
        ts, printers = _PRINTER_CACHE
        if (now - ts) <= max(0.0, float(ttl_seconds)):
            return list(printers)
    printers = discover_printers()
    _PRINTER_CACHE = (now, list(printers))
    return list(printers)


def evaluate_printer_status(
    available: list[PrinterInfo],
    configured_names: list[str],
) -> PrinterStatus:
    """Determine traffic-light status based on available vs configured printers."""
    if not configured_names:
        if not available:
            return PrinterStatus.RED
        return PrinterStatus.GREEN

    available_names = {p.name for p in available}
    matched = [n for n in configured_names if n in available_names]

    if not matched:
        return PrinterStatus.RED
    if len(matched) < len(configured_names):
        return PrinterStatus.YELLOW
    return PrinterStatus.GREEN
