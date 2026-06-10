"""Unit tests for ProductFieldBulkService."""
import pytest

from xw_studio.services.inventory.service import ProductRow
from xw_studio.services.products.field_bulk_service import (
    FieldOperatorType,
    ProductFieldBulkService,
)
from xw_studio.services.wix.product_details_client import UpdateResult


class _FakeInventoryService:
    def __init__(self, rows: list[ProductRow]) -> None:
        self._rows = rows

    def list_products(self) -> list[ProductRow]:
        return list(self._rows)

    def save_products(self, rows: list[ProductRow]) -> None:
        self._rows = list(rows)


class _FakeWixClient:
    """Minimal stub matching WixProductDetailsClient public surface."""

    def __init__(self) -> None:
        # Maps product_id -> (wix_field, value)
        self.updated_fields: dict[str, tuple[str, object]] = {}
        self.bulk_calls: list[dict] = []

    def has_credentials(self) -> bool:
        return True

    # Field-specific methods
    def update_product_price(self, pid: str, *, price: float) -> UpdateResult:
        self.updated_fields[pid] = ("price", price)
        return UpdateResult(requested=1, succeeded=1)

    def update_product_compare_at_price(self, pid: str, *, compare_at_price: float | None) -> UpdateResult:
        self.updated_fields[pid] = ("compareAtPrice", compare_at_price)
        return UpdateResult(requested=1, succeeded=1)

    def update_product_cost(self, pid: str, *, cost: float) -> UpdateResult:
        self.updated_fields[pid] = ("cost", cost)
        return UpdateResult(requested=1, succeeded=1)

    def update_product_weight(self, pid: str, *, weight: float) -> UpdateResult:
        self.updated_fields[pid] = ("weight", weight)
        return UpdateResult(requested=1, succeeded=1)

    def update_product_visible(self, pid: str, *, visible: bool) -> UpdateResult:
        self.updated_fields[pid] = ("visible", visible)
        return UpdateResult(requested=1, succeeded=1)

    def update_product_name(self, pid: str, *, name: str) -> UpdateResult:
        self.updated_fields[pid] = ("name", name)
        return UpdateResult(requested=1, succeeded=1)

    def update_product_description(self, pid: str, *, description: str) -> UpdateResult:
        self.updated_fields[pid] = ("description", description)
        return UpdateResult(requested=1, succeeded=1)

    def update_product_ribbon(self, pid: str, *, ribbon: str) -> UpdateResult:
        self.updated_fields[pid] = ("ribbon", ribbon)
        return UpdateResult(requested=1, succeeded=1)

    def update_product_brand(self, pid: str, *, brand_name: str) -> UpdateResult:
        self.updated_fields[pid] = ("brand", brand_name)
        return UpdateResult(requested=1, succeeded=1)

    def bulk_update_property(self, product_ids: list[str], *, field: str, value: object) -> UpdateResult:
        self.bulk_calls.append({"ids": list(product_ids), "field": field, "value": value})
        for pid in product_ids:
            self.updated_fields[pid] = (field, value)
        return UpdateResult(requested=len(product_ids), succeeded=len(product_ids))


def _make_test_row(sku: str, price: str = "10.00", brand: str = "TestBrand") -> ProductRow:
    return ProductRow(
        sku=sku,
        name=f"Product {sku}",
        category="TestCat",
        on_hand=5,
        price_eur=price,
        wix_id=f"wix-{sku}",
        sevdesk_id="",
        brand_name=brand,
        brand_id="",
        print_file_path="",
        print_profile_id="",
        print_plan=[],
        title_print_configs={},
    )


def test_field_bulk_service_set_price() -> None:
    """Test setting price to exact value."""
    rows = [
        _make_test_row("SKU1", "10.00"),
        _make_test_row("SKU2", "20.00"),
    ]
    inv = _FakeInventoryService(rows)
    wix = _FakeWixClient()
    service = ProductFieldBulkService(inv, wix)

    # Preview
    preview = service.preview_field_update(
        skus=["SKU1", "SKU2"],
        field_name="price_eur",
        operator=FieldOperatorType.SET.value,
        value="15.50",
    )
    assert preview.requested == 2
    assert preview.changed == 2
    assert preview.skipped == 0
    assert preview.dry_run is True

    # Apply without Wix
    report = service.apply_field_update(
        skus=["SKU1", "SKU2"],
        field_name="price_eur",
        operator=FieldOperatorType.SET.value,
        value="15.50",
        sync_wix=False,
    )
    assert report.changed == 2
    assert report.wix_attempted == 0
    assert report.wix_updated == 0

    updated = inv.list_products()
    assert updated[0].price_eur == "15.5"
    assert updated[1].price_eur == "15.5"


def test_field_bulk_service_add_percent() -> None:
    """Test adding percentage to numeric field."""
    rows = [_make_test_row("SKU1", "100.00")]
    inv = _FakeInventoryService(rows)
    wix = _FakeWixClient()
    service = ProductFieldBulkService(inv, wix)

    # Add 10% to price
    report = service.apply_field_update(
        skus=["SKU1"],
        field_name="price_eur",
        operator=FieldOperatorType.ADD_PERCENT.value,
        value="10",
        sync_wix=False,
    )
    assert report.changed == 1

    updated = inv.list_products()
    # 100 * 1.10 = 110
    assert float(updated[0].price_eur) == pytest.approx(110.0)


def test_field_bulk_service_subtract_percent() -> None:
    """Test subtracting percentage from numeric field."""
    rows = [_make_test_row("SKU1", "100.00")]
    inv = _FakeInventoryService(rows)
    wix = _FakeWixClient()
    service = ProductFieldBulkService(inv, wix)

    # Subtract 10% from price
    report = service.apply_field_update(
        skus=["SKU1"],
        field_name="price_eur",
        operator=FieldOperatorType.SUBTRACT_PERCENT.value,
        value="10",
        sync_wix=False,
    )
    assert report.changed == 1

    updated = inv.list_products()
    # 100 * 0.90 = 90
    assert float(updated[0].price_eur) == pytest.approx(90.0)


def test_field_bulk_service_brand_set() -> None:
    """Test setting brand name."""
    rows = [
        _make_test_row("SKU1", brand="OldBrand"),
        _make_test_row("SKU2", brand="OldBrand"),
    ]
    inv = _FakeInventoryService(rows)
    wix = _FakeWixClient()
    service = ProductFieldBulkService(inv, wix)

    report = service.apply_field_update(
        skus=["SKU1"],
        field_name="brand_name",
        operator=FieldOperatorType.SET.value,
        value="NewBrand",
        sync_wix=False,
    )
    assert report.changed == 1

    updated = inv.list_products()
    assert updated[0].brand_name == "NewBrand"
    assert updated[1].brand_name == "OldBrand"


def test_field_bulk_service_stock_set() -> None:
    """Test setting stock quantity."""
    row = _make_test_row("SKU1", price="10.00")
    rows = [row._replace(on_hand=5) if hasattr(row, '_replace') else ProductRow(
        sku=row.sku,
        name=row.name,
        category=row.category,
        on_hand=5,
        price_eur=row.price_eur,
        wix_id=row.wix_id,
        sevdesk_id=row.sevdesk_id,
        brand_name=row.brand_name,
        brand_id=row.brand_id,
        print_file_path=row.print_file_path,
        print_profile_id=row.print_profile_id,
        print_plan=row.print_plan,
        title_print_configs=row.title_print_configs,
    )]
    inv = _FakeInventoryService(rows)
    wix = _FakeWixClient()
    service = ProductFieldBulkService(inv, wix)

    report = service.apply_field_update(
        skus=["SKU1"],
        field_name="on_hand",
        operator=FieldOperatorType.SET.value,
        value="42",
        sync_wix=False,
    )
    assert report.changed == 1

    updated = inv.list_products()
    assert updated[0].on_hand == 42


def test_field_bulk_service_skipped_no_change() -> None:
    """Test skipping when value doesn't change."""
    rows = [_make_test_row("SKU1", "10.0")]  # Use 10.0 so it matches when converted back
    inv = _FakeInventoryService(rows)
    wix = _FakeWixClient()
    service = ProductFieldBulkService(inv, wix)

    report = service.apply_field_update(
        skus=["SKU1"],
        field_name="price_eur",
        operator=FieldOperatorType.SET.value,
        value="10.0",
        sync_wix=False,
    )
    assert report.skipped == 1
    assert report.changed == 0


def test_field_bulk_service_wix_writeback() -> None:
    """Test Wix writeback when sync_wix=True."""
    rows = [_make_test_row("SKU1", "10.00")]
    inv = _FakeInventoryService(rows)
    wix = _FakeWixClient()
    service = ProductFieldBulkService(inv, wix)

    report = service.apply_field_update(
        skus=["SKU1"],
        field_name="price_eur",
        operator=FieldOperatorType.SET.value,
        value="25.00",
        sync_wix=True,
    )
    assert report.changed == 1
    assert report.wix_attempted == 1
    assert report.wix_updated == 1

    # Check that Wix was called with correct product ID and field
    assert "wix-SKU1" in wix.updated_fields
    field_name, value = wix.updated_fields["wix-SKU1"]
    assert field_name == "price"  # Dispatched via update_product_price
    assert float(value) == pytest.approx(25.0)


def test_field_bulk_service_invalid_operator() -> None:
    """Test error handling for invalid operator."""
    rows = [_make_test_row("SKU1", "10.00")]
    inv = _FakeInventoryService(rows)
    wix = _FakeWixClient()
    service = ProductFieldBulkService(inv, wix)

    # This should fail during preview/apply when computing the value
    report = service.apply_field_update(
        skus=["SKU1"],
        field_name="price_eur",
        operator="invalid_operator",  # type: ignore[arg-type]
        value="10.00",
    )
    # Should result in failed items
    assert report.failed > 0
    assert report.changed == 0


def test_field_bulk_service_percent_on_text_field() -> None:
    """Test error when using percentage operator on text field."""
    rows = [_make_test_row("SKU1", brand="OldBrand")]
    inv = _FakeInventoryService(rows)
    wix = _FakeWixClient()
    service = ProductFieldBulkService(inv, wix)

    # This should result in failed items
    report = service.apply_field_update(
        skus=["SKU1"],
        field_name="brand_name",
        operator=FieldOperatorType.ADD_PERCENT.value,
        value="10",
    )
    assert report.failed > 0
    assert report.changed == 0
