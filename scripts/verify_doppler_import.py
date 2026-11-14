"""Verify an ENV import without displaying secret values."""
from __future__ import annotations

import os
import sys

from dotenv import dotenv_values


def main() -> int:
    if len(sys.argv) > 2:
        print("Usage: verify_doppler_import.py [SOURCE_ENV_PATH]")
        return 2
    expected = dotenv_values(sys.argv[1]) if len(sys.argv) == 2 else {}
    missing = [name for name in expected if name not in os.environ]
    different = [
        name
        for name, value in expected.items()
        if name in os.environ and os.environ[name] != (value or "")
    ]
    required = (
        "DATABASE_URL",
        "DATABASE_PUBLIC_URL",
        "FERNET_MASTER_KEY",
        "XW_PRINT_CENTER_DATABASE_URL",
    )
    empty_required = [name for name in required if not os.environ.get(name)]
    print(
        f"Keys: {len(expected)}; missing: {len(missing)}; "
        f"different: {len(different)}; empty required: {len(empty_required)}"
    )
    return int(bool(missing or different or empty_required))


if __name__ == "__main__":
    raise SystemExit(main())
