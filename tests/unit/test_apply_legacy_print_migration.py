from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import ProductAsset, PrintRule
from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.product_hub import ProductHubRepository


def test_apply_legacy_print_migration_is_additive_and_preserves_settings(tmp_path: Path) -> None:
    database = tmp_path / "migration.sqlite"
    url = f"sqlite:///{database}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    product, variant = ProductHubRepository(factory).create_product(sku="XW-100", name="Piece")
    legacy_json = json.dumps([{
        "sku": "XW-100", "print_file_path": "C:/scores/piece.pdf",
        "print_profile_id": "noten_duplex", "print_plan": [{"range": "Alle Seiten"}],
        "min_stock_target": 8, "reprint_batch_qty": 4,
    }])
    with factory.begin() as session:
        session.add(SettingKV(key="inventory.products", value_json=legacy_json))

    result = subprocess.run(
        [sys.executable, "scripts/product_hub/apply_legacy_print_migration.py", "--database-url", url, "--apply", "--yes"],
        check=True, capture_output=True, text=True,
    )

    assert json.loads(result.stdout)["mirrored_print_assets"] == 1
    with factory() as session:
        asset = session.scalar(select(ProductAsset).where(ProductAsset.variant_id == variant.id))
        rule = session.scalar(select(PrintRule).where(PrintRule.variant_id == variant.id))
        setting = session.get(SettingKV, "inventory.products")
    assert asset is not None and asset.uri == "C:/scores/piece.pdf"
    assert rule is not None and rule.print_profile_id == "noten_duplex"
    assert setting is not None and setting.value_json == legacy_json
