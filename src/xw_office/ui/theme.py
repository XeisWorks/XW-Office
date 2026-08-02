"""Theme helpers for applying qt-material + local QSS overrides."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def _themes_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "resources" / "themes"


def _theme_override_path(theme_name: str) -> Path:
    qss_name = "light.qss" if "light" in theme_name.lower() else "dark.qss"
    return _themes_dir() / qss_name


def _resolve_material_theme(theme_name: str) -> str:
    """Resolve to a project-local XML theme if one exists, else a bundled qt-material name."""
    custom_path = _themes_dir() / f"{theme_name}.xml"
    if custom_path.exists():
        return str(custom_path)
    return f"{theme_name}.xml"


def apply_app_theme(app: QApplication, theme_name: str) -> None:
    """Apply qt-material theme and append local project overrides."""
    try:
        from qt_material import apply_stylesheet

        apply_stylesheet(app, theme=_resolve_material_theme(theme_name))
    except Exception as exc:  # pragma: no cover - UI fallback
        logger.warning("Theme switch failed: %s", exc)
        return

    override_path = _theme_override_path(theme_name)
    if not override_path.exists():
        logger.debug("Theme override file not found: %s", override_path)
        return

    try:
        override_qss = override_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read theme override %s: %s", override_path, exc)
        return

    if not override_qss.strip():
        return

    app.setStyleSheet(f"{app.styleSheet()}\n\n{override_qss}")
