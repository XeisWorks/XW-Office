"""List or manually reconcile an unknown invoice side-effect claim.

This tool only reads/writes the local SettingKV claim record. It never calls
sevDesk, Wix, Outlook, a printer, or any other external service. Choose
``failed`` only after external readback confirms the side effect did not occur;
that state enables a later retry. Before reconciling a ``running`` claim, verify
that no XW-Office process on any workstation is still executing that operation.

Examples::

    python scripts/invoice_processing/reconcile_claim.py list-unknown
    python scripts/invoice_processing/reconcile_claim.py list-open
    python scripts/invoice_processing/reconcile_claim.py --database-url <local-test-database> list-unknown
    python scripts/invoice_processing/reconcile_claim.py --database-url <local-test-database> list-open
    python scripts/invoice_processing/reconcile_claim.py reconcile \
        --invoice-id 123 --operation invoice_mail --operation-id <exact-id> \
        --state succeeded --reconciled-by "Name" --evidence "Provider readback ..." \
        --confirm-operation-id <exact-id>

The database URL is resolved from ``DATABASE_PUBLIC_URL`` and then
``DATABASE_URL``, or can be supplied with ``--database-url`` for local use.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Literal, cast

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xw_office.repositories.settings_kv import SettingKvRepository  # noqa: E402
from xw_office.services.invoice_processing.operation_claims import (  # noqa: E402
    InvoiceOperationClaimStore,
    OperationClaim,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List or manually reconcile an unknown invoice side-effect claim.",
        epilog=(
            "This command only touches SettingKV. It never contacts sevDesk, Wix, "
            "Outlook, or a printer. Use state 'failed' only after confirming the "
            "external action did not occur."
        ),
    )
    parser.add_argument("--database-url", default="")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-unknown", help="unknown claims read-only auflisten")
    commands.add_parser(
        "list-open", help="running- und unknown-Claims read-only zur Pruefung auflisten"
    )
    reconcile = commands.add_parser(
        "reconcile",
        help="open claim nach externem Readback protokolliert abgleichen",
    )
    reconcile.add_argument("--invoice-id", required=True)
    reconcile.add_argument("--operation", required=True)
    reconcile.add_argument("--operation-id", required=True)
    reconcile.add_argument(
        "--expected-state",
        choices=("unknown", "running"),
        default="unknown",
        help="aktueller Claim-Status; running erfordert zusaetzliche Prozessbestaetigung",
    )
    reconcile.add_argument(
        "--state", required=True, choices=("succeeded", "failed")
    )
    reconcile.add_argument("--reconciled-by", required=True)
    reconcile.add_argument("--evidence", required=True)
    reconcile.add_argument(
        "--confirm-operation-id",
        required=True,
        help="muss exakt --operation-id entsprechen, um den Schreibvorgang zu bestätigen",
    )
    reconcile.add_argument(
        "--confirm-no-active-processes",
        default="",
        help="bei expected-state running muss dieser Wert exakt der Operation-ID entsprechen",
    )
    return parser


def _claim_dict(claim: OperationClaim) -> dict[str, Any]:
    return {
        "invoice_id": claim.invoice_id,
        "operation": claim.operation,
        "operation_id": claim.operation_id,
        "state": claim.state,
        "error": claim.error,
    }


def run_command(args: argparse.Namespace, repository: SettingKvRepository) -> int:
    """Execute a parsed command against an injected repository (never external APIs)."""
    store = InvoiceOperationClaimStore(repository)
    if args.command in {"list-unknown", "list-open"}:
        claims = store.list_unknown() if args.command == "list-unknown" else store.list_open()
        print(
            json.dumps(
                [_claim_dict(item) for item in claims],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    operation_id = str(args.operation_id).strip()
    if operation_id != str(args.confirm_operation_id).strip():
        raise ValueError("Bestaetigungs-ID muss exakt der Operation-ID entsprechen")
    expected_state = cast(Literal["unknown", "running"], str(args.expected_state))
    if expected_state == "running" and str(args.confirm_no_active_processes).strip() != operation_id:
        raise ValueError(
            "running-Claims erfordern eine exakte Bestaetigung, dass kein Prozess mehr aktiv ist"
        )
    claim = store.reconcile_open(
        str(args.invoice_id),
        str(args.operation),
        operation_id,
        args.state,
        reconciled_by=str(args.reconciled_by),
        evidence=str(args.evidence),
        expected_state=expected_state,
        no_active_processes_confirmed=expected_state != "running"
        or str(args.confirm_no_active_processes).strip() == operation_id,
    )
    print(json.dumps(_claim_dict(claim), ensure_ascii=False, indent=2))
    return 0


def _resolve_database_url(explicit: str = "") -> str:
    return (
        str(explicit or "").strip()
        or str(os.getenv("DATABASE_PUBLIC_URL") or "").strip()
        or str(os.getenv("DATABASE_URL") or "").strip()
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    database_url = _resolve_database_url(str(args.database_url))
    if not database_url:
        parser.error("DATABASE_URL/DATABASE_PUBLIC_URL oder --database-url ist erforderlich")
    engine = create_engine(database_url, pool_pre_ping=True, hide_parameters=True, future=True)
    factory = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
    try:
        return run_command(args, SettingKvRepository(factory))
    except Exception as exc:  # noqa: BLE001 - don't expose DB details or credentials
        print(
            f"Claim-Abgleich fehlgeschlagen ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
