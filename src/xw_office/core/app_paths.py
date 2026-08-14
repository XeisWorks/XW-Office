"""Central resolution of repo, log, state, and resource paths.

Independent of the current working directory, so it behaves the same whether
the app is started via the CMD launcher, the windowless GUI bootstrap, or a
test runner.
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

APP_USER_MODEL_ID = "at.xeisworks.xwoffice"


def find_repo_root() -> Path:
    """Walk up from this file to find the repo root (pyproject.toml or .git)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return current.parents[3]


def logs_dir() -> Path:
    return find_repo_root() / "logs"


def log_file_path() -> Path:
    return logs_dir() / "xw_office.log"


def bootstrap_log_file_path() -> Path:
    return logs_dir() / "xw_office_bootstrap.log"


def crash_log_file_path() -> Path:
    return logs_dir() / "xw_office_crash.log"


def update_log_file_path() -> Path:
    return logs_dir() / "xw_office_update.log"


def state_dir() -> Path:
    return find_repo_root() / "state"


def resources_dir() -> Path:
    return find_repo_root() / "resources"


def config_dir() -> Path:
    return find_repo_root() / "config"


def icons_dir() -> Path:
    return find_repo_root() / "icons"


def app_icon_path() -> Path:
    return icons_dir() / "xw_office.ico"


def ensure_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Give this process its own Windows taskbar identity. No-op off Windows."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass
