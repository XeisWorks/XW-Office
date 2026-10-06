"""Windowless bootstrap with visible, logged startup failures."""
from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import sys


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    try:
        os.chdir(root)
        sys.path.insert(0, str(root / "src"))
        (root / "logs").mkdir(exist_ok=True)
        logging.basicConfig(
            filename=str(root / "logs" / "xw_print_center_bootstrap.log"),
            level=logging.INFO, encoding="utf-8",
        )
        from xw_office.print_center.__main__ import main as start

        start()
    except Exception as exc:
        logging.exception("Print center startup failed")
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(
                0, f"Das Druckcenter konnte nicht gestartet werden:\n\n{exc}\n\n"
                "Details: logs\\xw_print_center_bootstrap.log",
                "XeisWorks Druckcenter", 0x10,
            )
        else:
            raise


if __name__ == "__main__":
    main()
