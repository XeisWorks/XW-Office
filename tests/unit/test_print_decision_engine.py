from __future__ import annotations

import json

from xw_office.services.products.catalog import ProductCatalogService
from xw_office.services.products.print_decision import (
    PieceBlock,
    PrintDecisionEngine,
    resolve_piece_print_config,
)
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


class _SnapshotPartClientStub:
    def get_cached_part_stock(self, part_id: str) -> int | None:
        return 9 if part_id == "part-1" else None

    def get_cached_part_by_sku(self, _sku: str):
        return None

    def get_part_stock(self, _part_id: str) -> int:
        raise AssertionError("piece rendering must not make an individual stock request")


def test_cached_piece_is_refreshed_from_same_title_specific_print_config(tmp_path) -> None:
    pdf_path = tmp_path / "Vielen Dank fuer die Blumen.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    repo = _RepoStub(
        {
            "inventory.products": json.dumps(
                [
                    {
                        "sku": "XW-010",
                        "name": "Diverse Noten",
                        "print_file_path": "",
                        "print_profile_id": "",
                        "print_plan": [],
                        "title_print_configs": {
                            "Vielen Dank für die Blumen": {
                                "path": str(pdf_path),
                                "profile_id": "",
                                "print_plan": [{"range": "Alle Seiten", "profile_id": "noten_a5"}],
                            }
                        },
                    }
                ],
                ensure_ascii=False,
            )
        }
    )
    cached_piece = PieceBlock(
        sku="xw-010",
        name="Vielen Dank fur die Blumen",
        qty_needed=1,
    )

    resolved = resolve_piece_print_config(ProductCatalogService(repo), cached_piece)

    assert resolved is cached_piece
    assert resolved.name == "Vielen Dank für die Blumen"
    assert resolved.print_file_path == pdf_path
    assert resolved.print_plan == [{"range": "Alle Seiten", "profile_id": "noten_a5"}]
    assert resolved.has_direct_print_config is True


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


def test_piece_blocks_use_stock_snapshot_without_individual_stock_requests() -> None:
    repo = _RepoStub(
        {
            "inventory.products": json.dumps(
                [
                    {
                        "sku": "XW-4-001",
                        "name": "Etuede A",
                        "sevdesk_id": "part-1",
                        "is_digital": False,
                    }
                ]
            )
        }
    )

    blocks = PrintDecisionEngine(
        ProductCatalogService(repo), _SnapshotPartClientStub()  # type: ignore[arg-type]
    ).get_piece_blocks([WixOrderItem(sku="XW-4-001", name="Etuede A", qty=2)])

    assert blocks[0].stock_status is not None
    assert blocks[0].stock_status.on_hand == 9


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


def test_xw_010_expands_multiline_titles_and_uses_canonical_title_configs(tmp_path) -> None:
    gabriellas_pdf = tmp_path / "Gabriellas Song BH.pdf"
    augen_pdf = tmp_path / "In deinen Augen BH.pdf"
    gabriellas_pdf.write_bytes(b"%PDF-1.4 gabriellas")
    augen_pdf.write_bytes(b"%PDF-1.4 augen")
    repo = _RepoStub(
        {
            "inventory.products": json.dumps(
                [
                    {
                        "sku": "XW-010",
                        "name": "Diverse Noten unveroeffentlicht",
                        "print_file_path": "",
                        "print_profile_id": "noten_a4_duplex",
                        "print_plan": [{"range": "Alle Seiten", "profile_id": "noten_a4_duplex"}],
                        "title_print_configs": {
                            "Gabriellas Song": {"path": str(gabriellas_pdf), "profile_id": "noten_simplex"},
                            "In deinen Augen": {"path": str(augen_pdf), "profile_id": "noten_duplex"},
                        },
                    }
                ]
            )
        }
    )

    blocks = PrintDecisionEngine(ProductCatalogService(repo), _PartClientStub()).get_piece_blocks(
        [
            WixOrderItem(
                sku="XW-010",
                name="Gabriellas Song\nIn deinen Augen",
                qty=2,
                is_unreleased=True,
                custom_piece_titles=["da Blechhauf'n - Gabriella's Song", "In deinen Augen"],
            )
        ]
    )

    assert [(block.name, block.qty_needed, block.print_file_path, block.print_profile_id) for block in blocks] == [
        ("Gabriellas Song", 1, gabriellas_pdf, "noten_simplex"),
        ("In deinen Augen", 1, augen_pdf, "noten_duplex"),
    ]


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
