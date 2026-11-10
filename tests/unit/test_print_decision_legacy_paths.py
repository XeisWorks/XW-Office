from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
import time
from collections.abc import Generator

from xw_office.services.products.catalog import Product, ProductCatalogService
from xw_office.services.products.print_decision import PieceBlock, PrintDecisionEngine
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


def test_concurrent_print_stock_updates_for_same_part_are_serialized() -> None:
    class ConcurrentPartClient(_PartClientStub):
        def __init__(self) -> None:
            self.stock = 5
            self._state_lock = Lock()
            self._active_reads = 0
            self.max_active_reads = 0

        def get_part_stock(self, _part_id: str) -> int:
            with self._state_lock:
                self._active_reads += 1
                self.max_active_reads = max(self.max_active_reads, self._active_reads)
                observed_stock = self.stock
            time.sleep(0.03)
            with self._state_lock:
                self._active_reads -= 1
            return observed_stock

        def set_part_stock(self, _part_id: str, new_stock: int) -> None:
            with self._state_lock:
                self.stock = new_stock

    part_client = ConcurrentPartClient()
    engine = PrintDecisionEngine(ProductCatalogService(_RepoStub("[]")), part_client)
    piece = PieceBlock(
        sku="XW-1",
        name="Testprodukt",
        qty_needed=2,
        product=Product(
            id="product-1", sku="XW-1", name="Testprodukt", sevdesk_part_id="part-1"
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: engine.record_print_and_update_sevdesk(piece, 2), range(2)))

    assert sorted(results) == [7, 9]
    assert part_client.stock == 9
    assert part_client.max_active_reads == 1


def test_separate_engines_share_part_stock_lock() -> None:
    class SharedLockRepository:
        def __init__(self) -> None:
            self._guard = Lock()
            self._locks: dict[str, Lock] = {}

        @contextmanager
        def advisory_lock(self, key: str) -> Generator[None, None, None]:
            with self._guard:
                lock = self._locks.setdefault(key, Lock())
            with lock:
                yield

    class ConcurrentPartClient(_PartClientStub):
        def __init__(self) -> None:
            self.stock = 5
            self._state_lock = Lock()
            self._active_reads = 0
            self.max_active_reads = 0

        def get_part_stock(self, _part_id: str) -> int:
            with self._state_lock:
                self._active_reads += 1
                self.max_active_reads = max(self.max_active_reads, self._active_reads)
                observed_stock = self.stock
            time.sleep(0.03)
            with self._state_lock:
                self._active_reads -= 1
            return observed_stock

        def set_part_stock(self, _part_id: str, new_stock: int) -> None:
            with self._state_lock:
                self.stock = new_stock

    shared_locks = SharedLockRepository()
    part_client = ConcurrentPartClient()
    catalog = ProductCatalogService(_RepoStub("[]"))
    engines = [
        PrintDecisionEngine(catalog, part_client, settings_repo=shared_locks),
        PrintDecisionEngine(catalog, part_client, settings_repo=shared_locks),
    ]
    piece = PieceBlock(
        sku="XW-1",
        name="Testprodukt",
        qty_needed=2,
        product=Product(
            id="product-1", sku="XW-1", name="Testprodukt", sevdesk_part_id="part-1"
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda engine: engine.record_print_and_update_sevdesk(piece, 2), engines
            )
        )

    assert sorted(results) == [7, 9]
    assert part_client.stock == 9
    assert part_client.max_active_reads == 1
