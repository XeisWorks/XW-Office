"""Export Product-Hub inventory and cutover state to a JSON snapshot.

This is a repeatable, read-only rollback aid for the inventory cutover.  It is
not a substitute for a provider-native PostgreSQL backup: the snapshot captures
the application-level ledger, materialized stock, alert/task state, idempotency
bookings and sync queues so a human can inspect and archive them before a
production cutover.

Usage::

    python scripts/product_hub/export_inventory_snapshot.py \
        --database-url postgresql://... --out inventory-cutover.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sqlalchemy import create_engine, inspect, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from xw_office.models.inventory_alert_task import InventoryAlertTask  # noqa: E402
from xw_office.models.inventory_count import InventoryCountLine, InventoryCountSession  # noqa: E402
from xw_office.models.inventory_document_booking import InventoryDocumentBooking  # noqa: E402
from xw_office.models.inventory_external_mirror import InventoryExternalMirror  # noqa: E402
from xw_office.models.product_hub_inventory import (  # noqa: E402
    InventoryAlert,
    InventoryLocation,
    InventoryMovement,
    InventoryStock,
)
from xw_office.models.product_hub_sync import (  # noqa: E402
    ExternalPayloadArchive,
    OutboxEvent,
    SyncConflict,
    SyncCursor,
)
from xw_office.models.settings_kv import SettingKV  # noqa: E402
from xw_office.services.product_hub.inventory import InventoryV2Service  # noqa: E402


_TABLES = (
    InventoryLocation,
    InventoryStock,
    InventoryMovement,
    InventoryAlert,
    InventoryAlertTask,
    InventoryDocumentBooking,
    InventoryExternalMirror,
    InventoryCountSession,
    InventoryCountLine,
    SyncConflict,
    SyncCursor,
    OutboxEvent,
    ExternalPayloadArchive,
)
_OPERATIONAL_SETTING_KEYS = (
    "product_hub.sevdesk_invoice_feed_checkpoint.v1",
    "product_hub.sevdesk_invoice_feed_start.v1",
)


def _resolve_database_url(explicit: str = "") -> str:
    """Resolve a database URL without requiring it in process arguments."""
    return (
        str(explicit or "").strip()
        or str(os.getenv("XW_INVENTORY_DATABASE_URL") or "").strip()
        or str(os.getenv("DATABASE_PUBLIC_URL") or "").strip()
        or str(os.getenv("DATABASE_URL") or "").strip()
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if hasattr(value, "hex") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return str(value)
        except Exception:  # pragma: no cover - defensive serializer fallback
            pass
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        column.key: _json_value(getattr(row, column.key))
        for column in inspect(row).mapper.columns
    }


def export_snapshot(database_url: str, out_path: Path) -> dict[str, Any]:
    """Read all application-level cutover tables and write one JSON snapshot."""
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    snapshot: dict[str, Any] = {
        "snapshot_kind": "product_hub_inventory_cutover",
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tables": {},
    }
    with session_factory() as session:
        for model in _TABLES:
            rows = list(session.scalars(select(model)))
            snapshot["tables"][model.__tablename__] = [_row_to_dict(row) for row in rows]
            print(f"  {model.__tablename__}: {len(rows)} rows")
        settings = session.query(SettingKV).filter(SettingKV.key.in_(_OPERATIONAL_SETTING_KEYS)).all()
        snapshot["operational_settings"] = {
            row.key: row.value_json for row in settings if row.key in _OPERATIONAL_SETTING_KEYS
        }
        print(f"  operational_settings: {len(settings)} rows")
    source_audit = InventoryV2Service(session_factory).audit_inventory_sources()
    snapshot["source_audit"] = source_audit.as_dict()
    print(
        "  source_audit: "
        f"{source_audit.active_physical_count} active physical, "
        f"{source_audit.blocking_issue_count} blockers, "
        f"{source_audit.warning_count} warnings"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Inventory snapshot written to {out_path} ({out_path.stat().st_size} bytes)")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    database_url = _resolve_database_url(str(args.database_url))
    if not database_url:
        parser.error("DATABASE_URL/DATABASE_PUBLIC_URL oder --database-url ist erforderlich")
    export_snapshot(database_url, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
