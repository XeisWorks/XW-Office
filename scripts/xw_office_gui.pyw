"""Windowless entry point for the normal XW-Office desktop start.

Run with ``pythonw.exe`` (no console). Deliberately avoids importing anything
from the ``xw_office`` package at module scope, so a broken virtual
environment or a broken editable install can still be reported with a
visible message box instead of failing silently.
"""
from __future__ import annotations

import ctypes
import datetime
import os
import sys
import traceback
from pathlib import Path

APP_USER_MODEL_ID = "at.xeisworks.xwoffice"
MB_ICONERROR = 0x10


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _bootstrap_log_path(repo_root: Path) -> Path:
    log_dir = repo_root / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return log_dir / "xw_office_bootstrap.log"


def _log_bootstrap_error(log_path: Path, exc: BaseException) -> None:
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"\n[{datetime.datetime.now().isoformat(timespec='seconds')}] Bootstrap error\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=handle)
    except OSError:
        pass


def _show_error(title: str, message: str) -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_ICONERROR)
    except (AttributeError, OSError):
        pass


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def main() -> None:
    repo_root = _repo_root()
    os.chdir(repo_root)

    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    os.environ.setdefault("XW_OFFICE_START_MODE", "gui")

    bootstrap_log = _bootstrap_log_path(repo_root)
    _set_app_user_model_id()

    try:
        from xw_office.__main__ import main as app_main
    except Exception as exc:  # broken venv, missing deps, broken editable install
        _log_bootstrap_error(bootstrap_log, exc)
        _show_error(
            "XW-Office: Startfehler",
            "XW-Office konnte nicht gestartet werden (Import fehlgeschlagen).\n\n"
            f"{exc}\n\nDetails: {bootstrap_log}",
        )
        return

    try:
        app_main()
    except Exception as exc:  # unhandled error before/around QApplication
        _log_bootstrap_error(bootstrap_log, exc)
        _show_error(
            "XW-Office: Startfehler",
            "XW-Office wurde unerwartet beendet.\n\n"
            f"{exc}\n\nDetails: {bootstrap_log}",
        )


if __name__ == "__main__":
    main()
