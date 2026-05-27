from __future__ import annotations

import json

from xw_studio.core.config import AppConfig
from xw_studio.services.inventory.service import InventoryService


class _RepoStub:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.data.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self.data[key] = value_json


def test_import_legacy_print_data_persists_default_and_title_configs(monkeypatch, tmp_path) -> None:
    pdf_default = tmp_path / "default.pdf"
    pdf_title = tmp_path / "title.pdf"
    pdf_default.write_bytes(b"%PDF-1.4 default")
    pdf_title.write_bytes(b"%PDF-1.4 title")
    store_path = tmp_path / "inventory_store.json"
    store_path.write_text(
        json.dumps(
            {
                "records": {
                    "XW-6213": {
                        "name": "Sidonje Polka",
                        "category": "noten",
                        "sevdesk_part_id": "123",
                        "pdfs": [
                            {
                                "title": "Standard",
                                "path": str(pdf_default),
                                "is_default": True,
                                "profile_id": "noten_a4_duplex",
                                "print_plan": [{"range": "Alle Seiten", "profile_id": "noten_a4_duplex"}],
                            }
                        ],
                        "title_print_configs": {
                            "sidonje": {
                                "title": "Sidonje Polka",
                                "pdfs": [
                                    {
                                        "title": "Sidonje Polka",
                                        "path": str(pdf_title),
                                        "is_default": True,
                                        "profile_id": "canon_brochure_mono",
                                        "print_plan": [{"range": "1-2", "profile_id": "canon_brochure_mono"}],
                                    }
                                ],
                            }
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XW_LEGACY_INVENTORY_STORE_PATH", str(store_path))
    repo = _RepoStub()
    svc = InventoryService(AppConfig(), repo)

    report = svc.import_legacy_print_data()

    assert report.products_updated == 1
    raw = json.loads(repo.data["inventory.products"])
    assert len(raw) == 1
    row = raw[0]
    assert row["sku"] == "XW-6213"
    assert row["print_file_path"] == str(pdf_default)
    assert row["print_profile_id"] == "noten_a4_duplex"
    assert row["print_plan"] == [{"range": "Alle Seiten", "profile_id": "noten_a4_duplex"}]
    assert row["title_print_configs"]["Sidonje Polka"]["path"] == str(pdf_title)


def test_save_product_print_config_persists_title_and_default_when_missing() -> None:
    repo = _RepoStub()
    svc = InventoryService(AppConfig(), repo)

    svc.save_product_print_config(
        sku="xw-4553",
        name="Test Title",
        print_file_path="C:/scores/test.pdf",
        print_profile_id="noten_duplex",
        print_plan=[{"range": "Alle Seiten", "profile_id": "noten_duplex"}],
    )

    rows = svc.list_products()
    assert len(rows) == 1
    row = rows[0]
    assert row.sku == "XW-4553"
    assert row.print_file_path == "C:/scores/test.pdf"
    assert row.print_profile_id == "noten_duplex"
    assert row.title_print_configs == {
        "Test Title": {
            "path": "C:/scores/test.pdf",
            "profile_id": "noten_duplex",
            "print_plan": [{"range": "Alle Seiten", "profile_id": "noten_duplex"}],
        }
    }
