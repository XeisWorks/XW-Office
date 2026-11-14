"""Start a desktop entry point with secrets supplied by Doppler."""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT = "xw-office-desktop"
CONFIG = "prd"
ENTRY_POINTS = {
    "office": "xw_office_gui.pyw",
    "print-center": "xw_print_center_gui.pyw",
}


def _doppler_executable() -> str | None:
    found = shutil.which("doppler")
    if found:
        return found
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        for candidate in packages.glob("Doppler.doppler_*/doppler.exe"):
            if candidate.is_file():
                return str(candidate)
    return None


def _show_error(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, message, "XW-Office: Doppler-Start", 0x10)
    else:
        print(message, file=sys.stderr)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    entry_point = ENTRY_POINTS.get(mode)
    if entry_point is None:
        _show_error("Ungueltiger XW-Office-Startmodus.")
        return 2

    doppler = _doppler_executable()
    if doppler is None:
        _show_error("Doppler CLI fehlt. Bitte Doppler installieren und erneut starten.")
        return 1

    repo_root = Path(__file__).resolve().parent.parent
    child = repo_root / "scripts" / entry_point
    if not child.is_file():
        _show_error("XW-Office-Startdatei fehlt. Bitte Installation pruefen.")
        return 1

    try:
        result = subprocess.run(
            [
                doppler,
                "run",
                "--no-fallback",
                "--project",
                PROJECT,
                "--config",
                CONFIG,
                "--",
                sys.executable,
                str(child),
            ],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except OSError:
        _show_error("Doppler konnte nicht gestartet werden. Bitte Installation pruefen.")
        return 1
    if result.returncode:
        _show_error(
            "XW-Office konnte nicht mit Doppler gestartet werden. "
            "Bitte Doppler-Anmeldung und Internetverbindung pruefen oder den Debug-Start verwenden."
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
