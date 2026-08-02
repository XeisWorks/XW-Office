"""Reisekosten module — embedded submodule (Phase 4)."""
from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)

_BRIDGE_CANDIDATES: list[tuple[str, str]] = [
    ("reisekosten.bridge", "create_widget"),
    ("reisekosten.bridge", "build_widget"),
    ("reisekosten.ui.bridge", "create_widget"),
    ("reisekosten.ui.bridge", "build_widget"),
    ("reisekosten.ui.main", "TravelCostsWidget"),
]


def load_travel_costs_widget() -> tuple[QWidget | None, list[str]]:
    """Try to load an embedded Reisekosten widget from optional submodule."""
    attempts: list[str] = []
    for module_name, symbol_name in _BRIDGE_CANDIDATES:
        marker = f"{module_name}:{symbol_name}"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            attempts.append(f"missing {marker}")
            continue
        symbol = getattr(module, symbol_name, None)
        if symbol is None:
            attempts.append(f"no-symbol {marker}")
            continue
        try:
            if isinstance(symbol, type) and issubclass(symbol, QWidget):
                widget = symbol()
            elif callable(symbol):
                widget = symbol()
            else:
                attempts.append(f"not-callable {marker}")
                continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reisekosten bridge failed for %s: %s", marker, exc)
            attempts.append(f"error {marker}: {exc}")
            continue
        if isinstance(widget, QWidget):
            return widget, attempts
        attempts.append(f"invalid-widget {marker}")
    return None, attempts


class TravelCostsView(QWidget):
    """Placeholder until Reisekosten repo is added as git submodule + bridge QWidget."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ = container
        layout = QVBoxLayout(self)
        embedded, attempts = load_travel_costs_widget()
        if embedded is not None:
            layout.addWidget(embedded)
        else:
            logger.info("Reisekosten bridge not loaded. Attempts: %s", "; ".join(attempts))
            label = QLabel(
                "Reisekosten-Modul:\n\n"
                "Externe Bridge aktuell nicht gefunden.\n"
                "Die App laeuft absichtlich ohne Submodule weiter.\n\n"
                "Einbindung vorbereiten:\n"
                "1) Git-Submodule: git submodule add https://github.com/XeisWorks/Reisekosten.git reisekosten\n"
                "2) Bridge exportieren, z. B. reisekosten.bridge:create_widget() -> QWidget\n"
                "3) Danach wird das Widget automatisch geladen."
            )
            label.setWordWrap(True)
            label.setStyleSheet("font-size: 14px; color: #888; padding: 24px;")
            layout.addWidget(label)
        layout.addStretch()
