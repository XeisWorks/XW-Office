"""Additively mirror approved legacy print data into Product Hub.

This command never changes ``setting_kv.inventory.products`` and never contacts a
provider.  By default it is a dry run; ``--apply --yes`` is required for database
writes. Exact SKU/alias matches only are eligible.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from xw_office.models.product_hub import ProductAsset, ProductSkuAlias, ProductVariant, PrintRule  # noqa: E402
from xw_office.models.settings_kv import SettingKV  # noqa: E402
from xw_office.repositories.product_hub import normalize_sku  # noqa: E402


def _text(value: object) -> str:
    return str(value or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--apply", action="store_true", help="Perform the additive Hub writes")
    parser.add_argument("--yes", action="store_true", help="Confirm the approved migration")
    args = parser.parse_args()
    if args.apply and not args.yes:
        parser.error("--apply requires --yes")

    engine = create_engine(args.database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory.begin() as session:
        settings = session.get(SettingKV, "inventory.products")
        legacy = json.loads(settings.value_json) if settings else []
        if not isinstance(legacy, list):
            raise RuntimeError("setting_kv inventory.products must be a JSON array")
        sku_counts = Counter(normalize_sku(_text(row.get("sku"))) for row in legacy if isinstance(row, dict))
        variants = list(session.scalars(select(ProductVariant)))
        variants_by_sku = {normalize_sku(row.sku): row for row in variants}
        defaults = {row.product_id: row for row in variants if row.is_default}
        aliases = {normalize_sku(row.alias_sku): row for row in session.scalars(select(ProductSkuAlias))}
        existing_assets = {
            (asset.product_id, asset.variant_id, asset.uri.strip())
            for asset in session.scalars(select(ProductAsset).where(ProductAsset.role == "PRINT_PDF"))
        }
        existing_rules = {
            rule.variant_id: rule for rule in session.scalars(select(PrintRule))
        }
        mirrored_assets = created_rules = skipped_rules = unmatched = 0
        for row in legacy:
            if not isinstance(row, dict):
                unmatched += 1
                continue
            sku = normalize_sku(_text(row.get("sku")))
            if not sku or sku_counts[sku] != 1:
                unmatched += 1
                continue
            variant = variants_by_sku.get(sku)
            if variant is None:
                alias = aliases.get(sku)
                variant = (
                    next((item for item in variants if item.id == alias.variant_id), None)
                    if alias and alias.variant_id
                    else defaults.get(alias.product_id) if alias else None
                )
            if variant is None:
                unmatched += 1
                continue
            path = _text(row.get("print_file_path"))
            asset_key = (variant.product_id, variant.id, path)
            product_asset_key = (variant.product_id, None, path)
            if path and asset_key not in existing_assets and product_asset_key not in existing_assets:
                mirrored_assets += 1
                if args.apply:
                    session.add(ProductAsset(
                        id=uuid.uuid4(), product_id=variant.product_id, variant_id=variant.id,
                        role="PRINT_PDF", storage_kind="NETWORK_PATH", uri=path,
                        source_channel="legacy_inventory", public_share_allowed=False,
                        health_status="unknown", row_version=1,
                    ))
                    existing_assets.add(asset_key)
            if variant.id in existing_rules:
                skipped_rules += 1
                continue
            profile = _text(row.get("print_profile_id"))
            plan = row.get("print_plan") if isinstance(row.get("print_plan"), list) else []
            if profile or plan or row.get("min_stock_target") is not None or row.get("reprint_batch_qty") is not None:
                created_rules += 1
                if args.apply:
                    session.add(PrintRule(
                        id=uuid.uuid4(), variant_id=variant.id,
                        min_stock_target=max(0, int(row.get("min_stock_target") or 5)),
                        reprint_batch_qty=max(0, int(row.get("reprint_batch_qty") or 3)),
                        print_profile_id=profile or None, print_plan=plan, row_version=1,
                    ))
        if not args.apply:
            session.rollback()
        print(json.dumps({
            "mode": "apply" if args.apply else "dry_run",
            "mirrored_print_assets": mirrored_assets,
            "created_print_rules": created_rules,
            "existing_print_rules_preserved": skipped_rules,
            "unmatched_or_ambiguous_legacy_rows": unmatched,
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
