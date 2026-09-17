"""Export the current Product Hub catalog to a single JSON snapshot file.

A minimal, reusable rollback aid — not a full Postgres backup (no ``pg_dump`` needed).
Used before destructive operations like ``replace_master_seed_v2.py``'s catalog
replace, per its own "Backup/Snapshot ... vor destruktiver Änderung" requirement.

Usage::

    python scripts/product_hub/export_catalog_snapshot.py --database-url postgresql://... --out snapshot.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sqlalchemy import create_engine, inspect, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from xw_office.models.product_hub import (  # noqa: E402
    ChannelMapping,
    Product,
    ProductCategory,
    ProductIdentifier,
    ProductImprovement,
    ProductPrice,
    ProductSkuAlias,
    ProductTag,
    ProductVariant,
)

_TABLES = (
    Product,
    ProductVariant,
    ProductIdentifier,
    ProductPrice,
    ProductCategory,
    ProductTag,
    ProductSkuAlias,
    ProductImprovement,
    ChannelMapping,
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in inspect(row).mapper.columns:
        value = getattr(row, column.key)
        if isinstance(value, (datetime.datetime, datetime.date)):
            value = value.isoformat()
        else:
            try:
                json.dumps(value)
            except TypeError:
                value = str(value)
        result[column.key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    engine = create_engine(args.database_url, pool_pre_ping=True, future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    snapshot: dict[str, Any] = {"exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with session_factory() as session:
        for model in _TABLES:
            rows = list(session.scalars(select(model)))
            snapshot[model.__tablename__] = [_row_to_dict(row) for row in rows]
            print(f"  {model.__tablename__}: {len(rows)} rows")

    out_path = Path(args.out)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Snapshot written to {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
