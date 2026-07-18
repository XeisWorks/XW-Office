"""Smoke tests for ProductsView brand bulk flow."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container
from xw_studio.services.inventory.service import ProductRow
from xw_studio.services.products.brand_service import (
    BrandBulkUpdateReport,
    BrandUpdateItem,
    ProductBrandService,
)
from xw_studio.ui.modules.products.view import ProductsView


class _FakeBrandService(ProductBrandService):
    def __init__(self) -> None:
        self.preview_called = False
        self.apply_called = False
        self.last_args: tuple[list[str], str, bool, bool] | None = None

    def preview_local_brand_update(self, skus: list[str], new_brand: str) -> BrandBulkUpdateReport:
        self.preview_called = True
        return BrandBulkUpdateReport(
            requested=len(skus),
            changed=len(skus),
            skipped=0,
            failed=0,
            dry_run=True,
            items=[
                BrandUpdateItem(
                    sku=sku,
                    name="",
                    category="",
                    previous_brand="alt",
                    new_brand=new_brand,
                    status="would-change",
                )
                for sku in skus
            ],
        )

    def apply_brand_update(
        self,
        skus: list[str],
        new_brand: str,
        *,
        sync_wix: bool,
        create_missing_wix_brand: bool,
    ) -> BrandBulkUpdateReport:
        self.apply_called = True
        self.last_args = (list(skus), new_brand, sync_wix, create_missing_wix_brand)
        return BrandBulkUpdateReport(
            requested=len(skus),
            changed=len(skus),
            skipped=0,
            failed=0,
            dry_run=False,
            wix_attempted=len(skus) if sync_wix else 0,
            wix_updated=len(skus) if sync_wix else 0,
            wix_failed=0,
            wix_brand_resolved=sync_wix,
            wix_brand_created=sync_wix and create_missing_wix_brand,
            items=[],
        )


def test_products_brand_bulk_flow_smoke(qtbot: object, monkeypatch: object) -> None:
    # Avoid async sync loading in constructor; we manually feed the table.
    monkeypatch.setattr(ProductsView, "_load_sync_sources", lambda self, *args, **kwargs: None)

    container = Container(AppConfig())
    fake_service = _FakeBrandService()
    container.register(ProductBrandService, lambda _c: fake_service)

    view = ProductsView(container)
    qtbot.addWidget(view)

    row = ProductRow(
        sku="XW-900",
        name="Testprodukt",
        category="Kat",
        on_hand=1,
        price_eur="12.00",
        wix_id="w-900",
        sevdesk_id="",
        brand_name="Alt",
        brand_id="",
        print_file_path="",
        print_profile_id="",
        print_plan=[],
        title_print_configs={},
    )
    view._all_rows = [row]  # noqa: SLF001
    sync_row_type = __import__("xw_studio.ui.modules.products.view", fromlist=["_SyncRow"])._SyncRow
    view._sync_rows = [  # noqa: SLF001
        sync_row_type(
            sku="XW-900",
            name="Testprodukt",
            wix_id="w-900",
            sevdesk_id="",
            local_present=True,
            wix_present=True,
            sevdesk_present=False,
            local_stock=1,
            wix_stock=1,
            sevdesk_stock=None,
            local_brand="Alt",
            wix_brand="Alt",
            local_price="12.00",
            wix_price="12.00",
            sevdesk_price="",
            status="Wix + lokal, nicht in sevDesk",
            can_create_sevdesk=True,
        )
    ]
    view._populate_sync_table(view._sync_rows)  # noqa: SLF001
    view._sync_table.selectRow(0)  # noqa: SLF001

    monkeypatch.setattr("xw_studio.ui.modules.products.view.QInputDialog.getText", lambda *args, **kwargs: ("NeuBrand", True))

    answers = [
        int(__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes),
        int(__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes),
        int(__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes),
    ]

    def _question(*args, **kwargs):
        return answers.pop(0)

    monkeypatch.setattr("xw_studio.ui.modules.products.view.QMessageBox.question", _question)
    monkeypatch.setattr("xw_studio.ui.modules.products.view.QMessageBox.information", lambda *args, **kwargs: None)

    view._bulk_set_inventory_brand()  # noqa: SLF001

    qtbot.waitUntil(lambda: fake_service.apply_called, timeout=2000)
    assert fake_service.preview_called is True
    assert fake_service.apply_called is True
    assert fake_service.last_args is not None
    skus, brand, sync_wix, create_missing = fake_service.last_args
    assert skus == ["XW-900"]
    assert brand == "NeuBrand"
    assert sync_wix is True
    assert create_missing is True


def test_products_sync_action_click_smoke(qtbot: object, monkeypatch: object) -> None:
    monkeypatch.setattr(ProductsView, "_load_sync_sources", lambda self, *args, **kwargs: None)

    container = Container(AppConfig())
    view = ProductsView(container)
    qtbot.addWidget(view)
    view.show()

    sync_row_type = __import__("xw_studio.ui.modules.products.view", fromlist=["_SyncRow"])._SyncRow
    view._sync_rows = [  # noqa: SLF001
        sync_row_type(
            sku="XW-901",
            name="Klicktest",
            wix_id="w-901",
            sevdesk_id="",
            local_present=False,
            wix_present=True,
            sevdesk_present=False,
            local_stock=0,
            wix_stock=2,
            sevdesk_stock=None,
            local_brand="",
            wix_brand="Neu",
            local_price="",
            wix_price="10.00",
            sevdesk_price="",
            status="nur Wix",
            can_create_sevdesk=True,
        )
    ]
    view._populate_sync_table(view._sync_rows)  # noqa: SLF001

    calls: list[str] = []
    monkeypatch.setattr(view, "_create_selected_wix_product_in_sevdesk", lambda sku: calls.append(sku))

    model = view._sync_table.model()  # noqa: SLF001
    assert model is not None
    index = model.index(0, 9)
    rect = view._sync_table.visualRect(index)  # noqa: SLF001

    qtbot.mouseClick(view._sync_table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())  # noqa: SLF001

    assert calls == ["XW-901"]


def test_products_view_exposes_separate_print_and_production_actions(
    qtbot: object, monkeypatch: object
) -> None:
    monkeypatch.setattr(ProductsView, "_load_sync_sources", lambda self, *args, **kwargs: None)
    view = ProductsView(Container(AppConfig()))
    qtbot.addWidget(view)

    labels = {button.text(): button for button in view.findChildren(QPushButton)}

    assert "Auswahl drucken" in labels
    assert "Drucken + Bestand" in labels
    assert labels["Auswahl drucken"] is not labels["Drucken + Bestand"]
