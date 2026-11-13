"""Isolated main-thread entry point for Brother bPAC COM label printing."""
from __future__ import annotations

import json
import sys

from xw_office.services.printing.print_jobs import BrotherLbxLabelJob
from xw_office.services.printing.print_queue import _print_brother_lbx_direct


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Ungueltiger Etikettendruckauftrag")
        _print_brother_lbx_direct(BrotherLbxLabelJob(**payload))
    except Exception as exc:  # noqa: BLE001 - relay a concise error to the queue.
        print(f"Etikettendruck fehlgeschlagen: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
