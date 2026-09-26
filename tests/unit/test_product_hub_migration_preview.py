from xw_office.services.product_hub.migration_preview import (
    HubAliasSnapshot,
    HubPrintAssetSnapshot,
    HubVariantSnapshot,
    build_migration_preview,
    preview_payload,
)


def test_preview_matches_exact_sku_and_reports_missing_print_asset() -> None:
    entries = build_migration_preview(
        [{"sku": " xw-100 ", "name": "Piece", "print_file_path": "C:/scores/piece.pdf"}],
        variants=[HubVariantSnapshot("product-1", "variant-1", "XW-100")],
        aliases=[HubAliasSnapshot("product-1", "variant-1", "OLD-100")],
        print_assets=[],
    )

    assert entries[0].status == "matched"
    assert entries[0].match_method == "exact_sku"
    assert entries[0].print_status == "mirror_required"
    assert entries[0].alias_mappings == ["OLD-100"]


def test_preview_keeps_alias_match_and_title_configs_explicit() -> None:
    entries = build_migration_preview(
        [{"sku": "OLD-200", "title_print_configs": {"Alt": {"path": "a.pdf"}}}],
        variants=[HubVariantSnapshot("product-2", "variant-2", "XW-200", is_default=True)],
        aliases=[HubAliasSnapshot("product-2", None, "OLD-200")],
        print_assets=[],
    )

    assert entries[0].status == "matched"
    assert entries[0].match_method == "sku_alias"
    assert entries[0].title_print_config_count == 1
    assert any("Title-specific" in note for note in entries[0].notes)


def test_preview_does_not_choose_between_duplicate_legacy_skus() -> None:
    entries = build_migration_preview(
        [{"sku": "XW-300"}, {"sku": " xw-300 "}],
        variants=[HubVariantSnapshot("product-3", "variant-3", "XW-300")],
        aliases=[],
        print_assets=[],
    )

    assert [entry.status for entry in entries] == ["ambiguous_legacy_sku", "ambiguous_legacy_sku"]
    assert preview_payload(entries)["summary"]["by_status"] == {"ambiguous_legacy_sku": 2}


def test_preview_script_reads_database_without_changing_legacy_setting(tmp_path: Path) -> None:
    database = tmp_path / "preview.sqlite"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    legacy_json = json.dumps([{"sku": "XW-999", "print_file_path": "C:/missing.pdf"}])
    with engine.begin() as connection:
        connection.execute(SettingKV.__table__.insert().values(key="inventory.products", value_json=legacy_json))

    output = tmp_path / "preview.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/product_hub/preview_legacy_product_migration.py",
            "--database-url",
            f"sqlite:///{database}",
            "--out",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["legacy_rows"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))["entries"][0]["status"] == "unmatched"
    with engine.connect() as connection:
        assert connection.execute(SettingKV.__table__.select()).one().value_json == legacy_json
import json
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine

from xw_office.models.base import Base
from xw_office.models.settings_kv import SettingKV
