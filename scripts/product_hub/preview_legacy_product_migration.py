"""Generate a read-only legacy-settings -> Product-Hub migration preview.

Example:
    python scripts/product_hub/preview_legacy_product_migration.py \
      --database-url "$DATABASE_URL" --out docs/product_workflow/migration_preview.json

The script only selects from ``setting_kv`` and Product Hub tables.  It never
creates assets, aliases, products, or external provider records.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from xw_office.models.product_hub import ProductAsset, ProductSkuAlias, ProductVariant  # noqa: E402
from xw_office.models.settings_kv import SettingKV  # noqa: E402
from xw_office.services.product_hub.migration_preview import (  # noqa: E402
    HubAliasSnapshot,
    HubPrintAssetSnapshot,
    HubVariantSnapshot,
    build_migration_preview,
    preview_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Read-only database connection URL")
    parser.add_argument("--out", required=True, type=Path, help="JSON report path")
    args = parser.parse_args()

    engine = create_engine(args.database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
        setting = session.get(SettingKV, "inventory.products")
        try:
            legacy = json.loads(setting.value_json) if setting is not None else []
        except json.JSONDecodeError as exc:
            raise RuntimeError("setting_kv inventory.products is not valid JSON") from exc
        if not isinstance(legacy, list):
            raise RuntimeError("setting_kv inventory.products must be a JSON array")
        variants = [
            HubVariantSnapshot(str(row.product_id), str(row.id), row.sku, row.is_default)
            for row in session.scalars(select(ProductVariant))
        ]
        aliases = [
            HubAliasSnapshot(str(row.product_id), str(row.variant_id) if row.variant_id else None, row.alias_sku)
            for row in session.scalars(select(ProductSkuAlias))
        ]
        assets = [
            HubPrintAssetSnapshot(str(row.product_id), str(row.variant_id) if row.variant_id else None, row.uri)
            for row in session.scalars(select(ProductAsset).where(ProductAsset.role == "PRINT_PDF"))
        ]
        session.rollback()

    payload = preview_payload(build_migration_preview(legacy, variants=variants, aliases=aliases, print_assets=assets))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = payload["summary"]
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
