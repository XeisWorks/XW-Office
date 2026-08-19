from __future__ import annotations

import json

from xw_office.services.products.catalog import ProductCatalogService
from xw_office.services.products.print_decision import PrintDecisionEngine
from xw_office.services.wix.client import WixOrderItem


class _RepoStub:
    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    def get_value_json(self, key: str) -> str | None:
        return self._data.get(key)


class _PartClientStub:
    def find_part_by_sku(self, _sku: str):
        return None

    def get_part_stock(self, _part_id: str) -> int:
        return 0


def test_piece_block_uses_new_repo_print_config_for_title_specific_entry(tmp_path) -> None:
    pdf_path = tmp_path / "song-a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    repo = _RepoStub(
        {
            "inventory.products": json.dumps(
                [
                    {
                        "sku": "XW-010",
                        "name": "Basisprodukt",
                        "print_file_path": "",
                        "print_profile_id": "",
                        "print_plan": [],
                        "title_print_configs": {
                            "Song A": {
                                "path": str(pdf_path),
                                "profile_id": "noten_a4_duplex",
                                "print_plan": [{"range": "1-2", "profile_id": "canon_brochure_mono"}],
                            }
                        },
                    }
                ],
                ensure_ascii=False,
            )
        }
    )

    engine = PrintDecisionEngine(ProductCatalogService(repo), _PartClientStub())
    blocks = engine.get_piece_blocks([WixOrderItem(sku="XW-010", name="Song A", qty=1, is_unreleased=True)])

    assert len(blocks) == 1
    block = blocks[0]
    assert block.print_file_path is not None
    assert str(block.print_file_path) == str(pdf_path)
    assert block.print_profile_id == "noten_a4_duplex"
    assert block.print_plan == [{"range": "1-2", "profile_id": "canon_brochure_mono"}]
    assert block.has_direct_print_config is True


def test_title_overrides_for_sku_lists_saved_title_specific_plans() -> None:
    repo = _RepoStub(
        {
            "inventory.products": json.dumps(
                [
                    {
                        "sku": "XW-6612",
                        "name": "Standardtitel",
                        "print_file_path": "C:/pdfs/default.pdf",
                        "print_profile_id": "noten_simplex",
                        "print_plan": [],
                        "title_print_configs": {
                            "Song A": {"path": "C:/pdfs/a.pdf", "profile_id": "noten_duplex", "print_plan": []},
                            "Song B": {"path": "C:/pdfs/b.pdf", "profile_id": "brochure_mono", "print_plan": []},
                        },
                    }
                ],
                ensure_ascii=False,
            )
        }
    )

    catalog = ProductCatalogService(repo)

    assert catalog.title_overrides_for_sku("xw-6612") == ["Song A", "Song B"]
    assert catalog.title_overrides_for_sku("XW-UNKNOWN") == []


def test_piece_block_uses_legacy_normalized_title_matching(tmp_path) -> None:
    pdf_path = tmp_path / "die-ungewoehnliche.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    repo = _RepoStub(
        {
            "inventory.products": json.dumps(
                [
                    {
                        "sku": "XW-4513",
                        "name": "Die Ungewoehnliche",
                        "print_file_path": "",
                        "print_profile_id": "",
                        "print_plan": [],
                        "title_print_configs": {
                            "Die Ungewöhnliche": {
                                "path": str(pdf_path),
                                "profile_id": "noten_a4_duplex",
                                "print_plan": [{"range": "Alle Seiten", "profile_id": "noten_a4_duplex"}],
                            }
                        },
                    }
                ],
                ensure_ascii=False,
            )
        }
    )

    engine = PrintDecisionEngine(ProductCatalogService(repo), _PartClientStub())
    blocks = engine.get_piece_blocks([WixOrderItem(sku="XW-4513", name="Die Ungewohnliche", qty=1)])

    assert len(blocks) == 1
    block = blocks[0]
    assert block.print_file_path is not None
    assert str(block.print_file_path) == str(pdf_path)
    assert block.print_profile_id == "noten_a4_duplex"
    assert block.print_plan == [{"range": "Alle Seiten", "profile_id": "noten_a4_duplex"}]


def test_xw_010_fuzzy_title_resolves_matching_unreleased_pdf(tmp_path) -> None:
    folder = tmp_path / "17 Unreleased" / "01 BH"
    folder.mkdir(parents=True)
    default_pdf = folder / "Gabriellas Song BH.pdf"
    matched_pdf = folder / "Jubelkl\u00e4nge BH.pdf"
    default_pdf.write_bytes(b"%PDF-1.4 default")
    matched_pdf.write_bytes(b"%PDF-1.4 matched")
    repo = _RepoStub(
        {
            "inventory.products": json.dumps(
                [
                    {
                        "sku": "XW-010",
                        "name": "Diverse Noten unveroeffentlicht",
                        "print_file_path": str(default_pdf),
                        "print_profile_id": "noten_a4_duplex",
                        "print_plan": [{"range": "Alle Seiten", "profile_id": "noten_a4_duplex"}],
                        "title_print_configs": {},
                    }
                ]
            )
        }
    )

    engine = PrintDecisionEngine(ProductCatalogService(repo), _PartClientStub())
    blocks = engine.get_piece_blocks(
        [WixOrderItem(sku="XW-010", name="Junelkl\u00e4nge Marsch", qty=1, is_unreleased=True)]
    )

    assert len(blocks) == 1
    assert blocks[0].name == "Jubelkl\u00e4nge"
    assert blocks[0].print_file_path == matched_pdf
    assert blocks[0].print_profile_id == "noten_a4_duplex"


def test_xw_010_unknown_title_does_not_fall_back_to_unrelated_default_pdf(tmp_path) -> None:
    default_pdf = tmp_path / "Gabriellas Song BH.pdf"
    default_pdf.write_bytes(b"%PDF-1.4 default")
    repo = _RepoStub(
        {
            "inventory.products": json.dumps(
                [
                    {
                        "sku": "XW-010",
                        "name": "Diverse Noten unveroeffentlicht",
                        "print_file_path": str(default_pdf),
                        "print_profile_id": "noten_a4_duplex",
                        "print_plan": [{"range": "Alle Seiten", "profile_id": "noten_a4_duplex"}],
                        "title_print_configs": {},
                    }
                ]
            )
        }
    )

    catalog = ProductCatalogService(repo)

    assert catalog.resolve_print_config("XW-010", title="Vollkommen anderer Titel") == {}
