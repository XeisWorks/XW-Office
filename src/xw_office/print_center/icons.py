"""Shared printer identity for table actions, desktop and taskbar."""
from pathlib import Path

from PySide6.QtGui import QIcon


def printer_icon_path() -> Path:
    return Path(__file__).resolve().parents[3] / "icons" / "print_center.ico"


def printer_icon() -> QIcon:
    return QIcon(str(printer_icon_path()))
