"""Unit tests for ProductBrandService bulk brand updates."""
from __future__ import annotations

from dataclasses import dataclass

from xw_studio.services.inventory.service import ProductRow
from xw_studio.services.products.brand_service import ProductBrandService


class _InventoryStub:
    def __init__(self, rows: list[ProductRow]) -> None:
        self._rows = list(rows)

    def list_products(self) -> list[ProductRow]:
        return list(self._rows)

    def save_products(self, rows: list[ProductRow]) -> None:
        self._rows = list(rows)


@dataclass
class _WixUpdateCall:
    product_id: str
    brand_name: str
    brand_id: str


class _WixStub:
    def __init__(self) -> None:
        self.calls: list[_WixUpdateCall] = []
        self.fail_product_ids: set[str] = set()
        self._brands_before: list[dict[str, str]] = [{"id": "existing", "name": "Existing"}]

    def has_credentials(self) -> bool:
        return True

    def list_products(self) -> list[object]:
        return []

    def list_brands(self) -> list[dict[str, str]]:
        return list(self._brands_before)

    def ensure_brand(self, brand_name: str, *, create_if_missing: bool = True) -> str:
        if not create_if_missing:
            return ""
        return "brand-new"

    def update_product_brand(self, product_id: str, *, brand_name: str, brand_id: str = "") -> None:
        self.calls.append(_WixUpdateCall(product_id=product_id, brand_name=brand_name, brand_id=brand_id))
        if product_id in self.fail_product_ids:
            raise RuntimeError("boom")


def _row(*, sku: str, name: str, brand: str, wix_id: str) -> ProductRow:
    return ProductRow(
        sku=sku,
        name=name,
        category="kat",
        on_hand=3,
        price_eur="9.99",
        wix_id=wix_id,
        sevdesk_id="",
        brand_name=brand,
        brand_id="",
        print_file_path="",
        print_profile_id="",
        print_plan=[],
        title_print_configs={},
    )


def test_preview_and_apply_local_brand_update() -> None:
    inv = _InventoryStub(
        [
            _row(sku="XW-1", name="One", brand="Alt", wix_id="w1"),
            _row(sku="XW-2", name="Two", brand="Neu", wix_id="w2"),
        ]
    )
    wix = _WixStub()
    service = ProductBrandService(inv, wix)

    preview = service.preview_local_brand_update(["XW-1", "XW-2", "MISS"], "Neu")
    assert preview.requested == 3
    assert preview.changed == 1
    assert preview.skipped == 2

    report = service.apply_local_brand_update(["XW-1", "XW-2"], "Neu")
    assert report.changed == 1
    assert report.skipped == 1

    by_sku = {row.sku: row for row in inv.list_products()}
    assert by_sku["XW-1"].brand_name == "Neu"
    assert by_sku["XW-2"].brand_name == "Neu"


def test_apply_brand_update_with_wix_create_and_partial_failure() -> None:
    inv = _InventoryStub(
        [
            _row(sku="XW-1", name="One", brand="Alt", wix_id="w1"),
            _row(sku="XW-2", name="Two", brand="Alt", wix_id="w2"),
        ]
    )
    wix = _WixStub()
    wix.fail_product_ids.add("w2")
    service = ProductBrandService(inv, wix)

    report = service.apply_brand_update(
        ["XW-1", "XW-2"],
        "MegaBrand",
        sync_wix=True,
        create_missing_wix_brand=True,
    )

    assert report.changed == 2
    assert report.wix_attempted == 2
    assert report.wix_updated == 1
    assert report.wix_failed == 1
    assert report.wix_brand_resolved is True
    assert report.wix_brand_created is True

    assert len(wix.calls) == 2
    assert all(call.brand_name == "MegaBrand" for call in wix.calls)
    assert all(call.brand_id == "brand-new" for call in wix.calls)

    failed_items = [item for item in report.items if item.status == "failed"]
    assert len(failed_items) == 1
    assert failed_items[0].sku == "XW-2"
    assert "Wix-Writeback fehlgeschlagen" in failed_items[0].message
