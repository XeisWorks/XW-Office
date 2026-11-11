"""Evaluate Product-Hub inventory cutover readiness without changing state.

The command is intentionally read-only and fails closed.  It is suitable for a
deployment/operations gate before a human enables the inventory master flag.

Usage::

    python scripts/product_hub/check_inventory_cutover.py \
        --database-url postgresql://... --shadow-enabled --json

Exit codes: 0 when every readiness check is ``ready``; 2 when any check is
blocked or manual; 1 for configuration/runtime errors.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xw_office.services.product_hub.inventory import InventoryV2Service  # noqa: E402


def assess_cutover(
    database_url: str,
    *,
    shadow_enabled: bool = False,
    master_enabled: bool = False,
) -> dict[str, Any]:
    """Return the same readiness evidence as the web endpoint, without writes."""
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False, future=True)
    readiness = InventoryV2Service(
        factory,
        shadow_enabled=shadow_enabled,
        master_enabled=master_enabled,
    ).cutover_readiness()
    return {
        "master_enabled": readiness.master_enabled,
        "shadow_enabled": readiness.shadow_enabled,
        "eligible": readiness.eligible,
        "assessed_at": readiness.assessed_at.isoformat(),
        "checks": [
            {"code": check.code, "label": check.label, "state": check.state, "detail": check.detail}
            for check in readiness.checks
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--shadow-enabled", action="store_true")
    parser.add_argument("--master-enabled", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    try:
        payload = assess_cutover(
            str(args.database_url),
            shadow_enabled=bool(args.shadow_enabled),
            master_enabled=bool(args.master_enabled),
        )
    except Exception as exc:  # noqa: BLE001 - CLI must expose a stable failure code
        print(f"Cutover-Readiness konnte nicht ermittelt werden: {exc}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"eligible={payload['eligible']} shadow_enabled={payload['shadow_enabled']} master_enabled={payload['master_enabled']}")
        for check in payload["checks"]:
            print(f"[{check['state']}] {check['code']}: {check['detail']}")
    return 0 if payload["eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
