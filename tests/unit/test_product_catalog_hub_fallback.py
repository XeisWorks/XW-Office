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
