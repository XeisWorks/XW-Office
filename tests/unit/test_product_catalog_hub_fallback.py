from xw_office.services.product_hub.desktop_client import DesktopHubSnapshot
from xw_office.services.products.catalog import ProductCatalogService


class _HubClient:
    def get_product_snapshot_by_sku(self, _sku: str) -> DesktopHubSnapshot:
        return DesktopHubSnapshot(
            "v1",
            {"id": "product-1", "name": "Hub Piece", "product_type": "physical", "status": "live"},
            [{"id": "variant-1", "sku": "XW-1", "is_default": True, "print_rule": {
                "min_stock_target": 7, "reprint_batch_qty": 9,
                "print_profile_id": "noten_duplex", "print_plan": [{"range": "Alle Seiten"}],
            }}],
            [{"role": "PRINT_PDF", "storage_kind": "NETWORK_PATH", "variant_id": "variant-1", "uri": "C:/scores/piece.pdf", "sort_order": 0}],
        )


def test_catalog_prefers_hub_snapshot_for_print_data() -> None:
    catalog = ProductCatalogService(hub_client=_HubClient(), prefer_hub=True)

    product = catalog.resolve_sku("XW-1")

    assert product is not None
    assert product.id == "product-1"
    assert product.print_file_path.endswith("piece.pdf")
    assert product.print_rule.reprint_batch_qty == 9
    assert catalog.resolve_print_config("XW-1")["profile_id"] == "noten_duplex"


def test_catalog_warms_hub_product_cache_from_one_batch_snapshot() -> None:
    class BatchHubClient(_HubClient):
        def __init__(self) -> None:
            self.batch_calls: list[list[str]] = []
            self.single_calls = 0

        def get_product_snapshot_by_sku(self, _sku: str) -> DesktopHubSnapshot:
            self.single_calls += 1
            raise AssertionError("batch cache should satisfy the following SKU lookup")

        def get_product_snapshots_by_skus(self, skus: list[str]) -> dict[str, DesktopHubSnapshot]:
            self.batch_calls.append(skus)
            snapshot = _HubClient().get_product_snapshot_by_sku("XW-1")
            return {"XW-1": snapshot}

    hub = BatchHubClient()
    catalog = ProductCatalogService(hub_client=hub, prefer_hub=True)

    catalog.warm_hub_products([" xw-1 ", "XW-1", "MISSING"])
    product = catalog.resolve_sku("XW-1")
    assert catalog.resolve_sku("MISSING") is None

    assert hub.batch_calls == [["XW-1", "MISSING"]]
    assert hub.single_calls == 0
    assert product is not None
    assert product.id == "product-1"
