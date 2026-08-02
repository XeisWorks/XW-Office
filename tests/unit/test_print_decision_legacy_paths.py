from __future__ import annotations

from pathlib import Path

from xw_office.services.products.catalog import ProductCatalogService
from xw_office.services.products.print_decision import PrintDecisionEngine
from xw_office.services.wix.client import WixOrderItem


class _PartClientStub:
    def get_part_stock(self, _part_id: str) -> int:
        return 0

    def set_part_stock(self, _part_id: str, _stock: int) -> None:
        return None

    def find_part_by_sku(self, _sku: str):
        return None


class _RepoStub:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def get_value_json(self, key: str) -> str | None:
        return self._payload if key == "inventory.products" else None


def test_engine_uses_new_repo_inventory_pdf_paths(tmp_path: Path) -> None:
    repo_pdf = tmp_path / "piece.pdf"
    repo_pdf.write_bytes(b"%PDF-1.4\n")
    catalog = ProductCatalogService(
        _RepoStub(
            '[{"sku":"XW-4-123","name":"Test Piece","print_file_path":"'
            + str(repo_pdf).replace("\\", "\\\\")
            + '","print_profile_id":"noten_a4_duplex","print_plan":[{"range":"Alle Seiten","profile_id":"noten_a4_duplex"}]}]'
        )
    )

    engine = PrintDecisionEngine(catalog, _PartClientStub())  # type: ignore[arg-type]

    blocks = engine.get_piece_blocks(
        [WixOrderItem(line_item_id="l1", sku="XW-4-123", name="Test Piece", qty=1)],
        "RE-1",
    )

    assert blocks
    assert blocks[0].print_file_path is not None
    assert blocks[0].print_file_path == repo_pdf
