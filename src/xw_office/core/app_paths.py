"""Central resolution of repo, log, state, and resource paths.

Independent of the current working directory, so it behaves the same whether
the app is started via the CMD launcher, the windowless GUI bootstrap, or a
test runner.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

APP_USER_MODEL_ID = "at.xeisworks.xwoffice"
DEBUG_APP_USER_MODEL_ID = f"{APP_USER_MODEL_ID}.debug"


def office_app_user_model_id(start_mode: str) -> str:
    """Keep console diagnostics separate from the windowless taskbar launcher."""
    return DEBUG_APP_USER_MODEL_ID if start_mode == "debug" else APP_USER_MODEL_ID


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


def local_app_data_dir() -> Path:
    """Return the per-user data root for machine-local application state.

    Invoice collection state contains browser profiles, OAuth caches, temporary files and
    a local journal.  Those artifacts must never live below the repository or a OneDrive
    folder.  ``LOCALAPPDATA`` is the Windows source of truth; the non-Windows fallback keeps
    unit tests and development environments portable without changing the Windows layout.
    """
    configured = str(os.getenv("LOCALAPPDATA") or "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured))) / "XeisWorks" / "XW-Office"
    if sys.platform == "win32":
        profile = str(os.getenv("USERPROFILE") or "").strip()
        if profile:
            return Path(profile) / "AppData" / "Local" / "XeisWorks" / "XW-Office"
    return Path.home() / ".local" / "share" / "XeisWorks" / "XW-Office"


def invoice_collection_dir() -> Path:
    """Return the local, non-synchronised invoice-collection data root."""
    return local_app_data_dir() / "invoice_collection"


def default_invoice_target_dir() -> Path:
    """Return the conventional local OneDrive Business invoice target.

    The Windows profile name is deliberately resolved from the current user rather
    than embedded in the path, because the same repository is used on multiple PCs.
    """
    profile = str(os.getenv("USERPROFILE") or "").strip()
    root = Path(profile) if profile else Path.home()
    return root / "OneDrive - XeisWorks" / "00 Finanzmanagement" / "02 Belege"


def chrome_user_data_dir() -> Path:
    """Return the current user's normal Google Chrome profile root."""
    configured = str(os.getenv("LOCALAPPDATA") or "").strip()
    root = Path(configured) if configured else local_app_data_dir().parent.parent.parent
    return root / "Google" / "Chrome" / "User Data"


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
