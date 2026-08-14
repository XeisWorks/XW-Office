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
import subprocess
import sys
import traceback
from pathlib import Path

APP_USER_MODEL_ID = "at.xeisworks.xwoffice"
MB_ICONERROR = 0x10
MB_ICONQUESTION = 0x20
MB_YESNO = 0x04
IDYES = 6

GIT_TIMEOUT_LOCAL = 5
GIT_TIMEOUT_FETCH = 8
UPDATE_SCRIPT_TIMEOUT = 180


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


def _creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _git(repo_root: Path, args: list[str], timeout: int) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_creationflags(),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _update_available(repo_root: Path) -> bool:
    """Best-effort, fail-open check. Any doubt, any error, any timeout -> no update offered."""
    branch = _git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"], GIT_TIMEOUT_LOCAL)
    if branch is None or branch.returncode != 0 or branch.stdout.strip() != "main":
        return False

    upstream = _git(
        repo_root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], GIT_TIMEOUT_LOCAL
    )
    if upstream is None or upstream.returncode != 0 or upstream.stdout.strip() != "origin/main":
        return False

    status = _git(repo_root, ["status", "--porcelain"], GIT_TIMEOUT_LOCAL)
    if status is None or status.returncode != 0 or status.stdout.strip():
        return False  # dirty working tree: never touch it automatically

    fetch = _git(repo_root, ["fetch", "origin", "main"], GIT_TIMEOUT_FETCH)
    if fetch is None or fetch.returncode != 0:
        return False  # offline or unreachable: skip silently, never block the start

    diff = _git(repo_root, ["diff", "--quiet", "HEAD", "origin/main"], GIT_TIMEOUT_LOCAL)
    return diff is not None and diff.returncode != 0


def _ask_update_now() -> bool:
    if sys.platform != "win32":
        return False
    try:
        choice = ctypes.windll.user32.MessageBoxW(
            0,
            "Eine neue Version von XeisWorks Office ist verfuegbar.\n\n"
            "Jetzt aktualisieren (dauert meist nur wenige Sekunden)?\n"
            "\"Nein\" startet die aktuelle Version unveraendert.",
            "XeisWorks Office: Update verfuegbar",
            MB_YESNO | MB_ICONQUESTION,
        )
    except (AttributeError, OSError):
        return False
    return choice == IDYES


def _run_update(repo_root: Path) -> bool:
    update_script = repo_root / "scripts" / "update_xw_office.ps1"
    if not update_script.exists():
        return False
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(update_script),
                "-ExcludeProcessId",
                str(os.getpid()),
            ],
            capture_output=True,
            text=True,
            timeout=UPDATE_SCRIPT_TIMEOUT,
            creationflags=_creationflags(),
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _maybe_offer_update(repo_root: Path) -> None:
    """Silent, fail-open update check. Never delays or blocks the normal start beyond
    the short git timeouts above, and never touches a dirty or non-standard checkout."""
    if os.getenv("XW_OFFICE_SKIP_UPDATE_CHECK"):
        return
    try:
        if not _update_available(repo_root):
            return
        if not _ask_update_now():
            return
        if not _run_update(repo_root):
            _show_error(
                "XeisWorks Office: Update fehlgeschlagen",
                "Das automatische Update ist fehlgeschlagen. Details: "
                f"{repo_root / 'logs' / 'xw_office_update.log'}\n\n"
                "XeisWorks Office startet mit der bisherigen Version weiter.",
            )
    except Exception:
        pass  # the update check must never crash or block the normal start


def main() -> None:
    repo_root = _repo_root()
    os.chdir(repo_root)

    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    os.environ.setdefault("XW_OFFICE_START_MODE", "gui")

    bootstrap_log = _bootstrap_log_path(repo_root)
    _set_app_user_model_id()
    _maybe_offer_update(repo_root)

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
