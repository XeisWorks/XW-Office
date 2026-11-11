"""Evaluate Product-Hub inventory cutover readiness without changing state.

The command is intentionally read-only and fails closed.  It is suitable for a
deployment/operations gate before a human enables the inventory master flag.

Usage::

    python scripts/product_hub/check_inventory_cutover.py \
        --database-url postgresql://... --shadow-enabled --json

When ``--database-url`` is omitted, the command resolves the connection from
``XW_INVENTORY_DATABASE_URL``, then ``DATABASE_PUBLIC_URL`` and finally
``DATABASE_URL``.  This keeps Railway runs from exposing a DSN in the process
arguments while retaining the explicit argument for local use.

Exit codes: 0 when every readiness check is ``ready``; 2 when any check is
blocked or manual; 1 for configuration/runtime errors.
"""
from __future__ import annotations

import argparse
import json
import os
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
    checks = [
        {"code": check.code, "label": check.label, "state": check.state, "detail": check.detail}
        for check in readiness.checks
    ]
    checks.extend(_runtime_configuration_checks())
    eligible = bool(readiness.eligible and all(check["state"] == "ready" for check in checks))
    return {
        "master_enabled": readiness.master_enabled,
        "shadow_enabled": readiness.shadow_enabled,
        "eligible": eligible,
        "assessed_at": readiness.assessed_at.isoformat(),
        "checks": checks,
    }


def _runtime_configuration_checks() -> list[dict[str, str]]:
    """Return credential/service gates without exposing secret values."""
    missing_sevdesk = not str(os.getenv("SEVDESK_API_TOKEN") or "").strip()
    missing_graph = [
        key
        for key in ("MS_GRAPH_TENANT_ID", "MS_GRAPH_CLIENT_ID", "MS_GRAPH_MAILBOX")
        if not str(os.getenv(key) or "").strip()
    ]
    missing = (["SEVDESK_API_TOKEN"] if missing_sevdesk else []) + missing_graph
    return [
        {
            "code": "provider_credentials",
            "label": "sevDesk-/Graph-Zugangsdaten sind gesetzt",
            "state": "blocked" if missing_sevdesk or missing_graph else "ready",
            "detail": (
                "Fehlende Variablen: " + ", ".join(missing)
                if missing
                else "sevDesk- und Graph-Grundkonfiguration ist vorhanden."
            ),
        },
        {
            "code": "inventory_worker_service",
            "label": "Separater xw-inventory-worker ist aktiviert",
            "state": "manual",
            "detail": "Railway-Service-Aktivierung muss im Deployment nachgewiesen werden.",
        },
    ]


def _resolve_database_url(explicit: str = "") -> str:
    """Resolve a database URL without requiring it in process arguments."""
    return (
        str(explicit or "").strip()
        or str(os.getenv("XW_INVENTORY_DATABASE_URL") or "").strip()
        or str(os.getenv("DATABASE_PUBLIC_URL") or "").strip()
        or str(os.getenv("DATABASE_URL") or "").strip()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--shadow-enabled", action="store_true")
    parser.add_argument("--master-enabled", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    try:
        database_url = _resolve_database_url(str(args.database_url))
        if not database_url:
            parser.error(
                "DATABASE_URL/DATABASE_PUBLIC_URL oder --database-url ist erforderlich"
            )
        payload = assess_cutover(
            database_url,
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
