"""Smoke tests for ProductsView brand bulk flow."""
from __future__ import annotations

from threading import Event

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QPushButton

from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.services.inventory.service import ProductRow
from xw_office.services.products.catalog import Product, ProductCatalogService
from xw_office.services.products.brand_service import (
    BrandBulkUpdateReport,
    BrandUpdateItem,
    ProductBrandService,
)
from xw_office.ui.modules.products.view import ProductsView


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
    sync_row_type = __import__("xw_office.ui.modules.products.view", fromlist=["_SyncRow"])._SyncRow
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

    monkeypatch.setattr("xw_office.ui.modules.products.view.QInputDialog.getText", lambda *args, **kwargs: ("NeuBrand", True))

    answers = [
        int(__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes),
        int(__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes),
        int(__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes),
    ]

    def _question(*args, **kwargs):
        return answers.pop(0)

    monkeypatch.setattr("xw_office.ui.modules.products.view.QMessageBox.question", _question)
    monkeypatch.setattr("xw_office.ui.modules.products.view.QMessageBox.information", lambda *args, **kwargs: None)

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

    sync_row_type = __import__("xw_office.ui.modules.products.view", fromlist=["_SyncRow"])._SyncRow
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


def test_products_sync_print_action_opens_product_print_config(qtbot: object, monkeypatch: object) -> None:
    monkeypatch.setattr(ProductsView, "_load_sync_sources", lambda self, *args, **kwargs: None)

    container = Container(AppConfig())
    view = ProductsView(container)
    qtbot.addWidget(view)
    view.show()

    row = ProductRow(
        sku="XW-902",
        name="Drucktest",
        category="Kat",
        on_hand=1,
        price_eur="12.00",
        wix_id="w-902",
        sevdesk_id="s-902",
        brand_name="",
        brand_id="",
        print_file_path="",
        print_profile_id="",
        print_plan=[],
        title_print_configs={},
    )
    view._all_rows = [row]  # noqa: SLF001
    sync_row_type = __import__("xw_office.ui.modules.products.view", fromlist=["_SyncRow"])._SyncRow
    view._sync_rows = [  # noqa: SLF001
        sync_row_type(
            sku="XW-902",
            name="Drucktest",
            wix_id="w-902",
            sevdesk_id="s-902",
            local_present=True,
            wix_present=True,
            sevdesk_present=True,
            local_stock=1,
            wix_stock=1,
            sevdesk_stock=1,
            local_brand="",
            wix_brand="",
            local_price="12.00",
            wix_price="12.00",
            sevdesk_price="12.00",
            status="sauber verknuepft",
            can_create_sevdesk=False,
        )
    ]
    view._populate_sync_table(view._sync_rows)  # noqa: SLF001

    calls: list[str] = []
    monkeypatch.setattr(view, "_manage_product_print_config", lambda sku: calls.append(sku))

    model = view._sync_table.model()  # noqa: SLF001
    assert model is not None
    index = model.index(0, 10)
    rect = view._sync_table.visualRect(index)  # noqa: SLF001

    qtbot.mouseClick(view._sync_table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())  # noqa: SLF001

    assert calls == ["XW-902"]


def test_products_sync_ready_print_action_is_backgrounded_and_confirms_click(
    qtbot: object,
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(ProductsView, "_load_sync_sources", lambda self, *args, **kwargs: None)
    view = ProductsView(Container(AppConfig()))
    qtbot.addWidget(view)
    view.show()
    release = Event()
    started = Event()

    row = ProductRow(
        sku="XW-READY",
        name="Druckbereit",
        category="Kat",
        on_hand=1,
        price_eur="12.00",
        wix_id="w-ready",
        sevdesk_id="s-ready",
        print_file_path="ready.pdf",
        print_profile_id="noten_simplex",
        print_plan=[],
    )
    view._all_rows = [row]  # noqa: SLF001
    sync_row_type = __import__("xw_office.ui.modules.products.view", fromlist=["_SyncRow"])._SyncRow
    view._sync_rows = [  # noqa: SLF001
        sync_row_type(
            sku=row.sku,
            name=row.name,
            wix_id=row.wix_id,
            sevdesk_id=row.sevdesk_id,
            local_present=True,
            wix_present=True,
            sevdesk_present=True,
            local_stock=1,
            wix_stock=1,
            sevdesk_stock=1,
            local_brand="",
            wix_brand="",
            local_price="12.00",
            wix_price="12.00",
            sevdesk_price="12.00",
            status="sauber verknuepft",
            can_create_sevdesk=False,
        )
    ]
    view._populate_sync_table(view._sync_rows)  # noqa: SLF001

    def fake_prepare(*_args: object, **_kwargs: object):
        def job() -> None:
            started.set()
            release.wait(timeout=2)

        return job

    monkeypatch.setattr(
        "xw_office.ui.modules.products.view.prepare_piece_pdf_print",
        fake_prepare,
    )
    monkeypatch.setattr(QInputDialog, "getInt", lambda *_args, **_kwargs: (2, True))

    model = view._sync_table.model()  # noqa: SLF001
    assert model is not None
    index = model.index(0, 10)
    rect = view._sync_table.visualRect(index)  # noqa: SLF001
    qtbot.mouseClick(view._sync_table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())  # noqa: SLF001

    row_data = view._sync_table.source_rows_data()[0]  # noqa: SLF001
    assert row_data["__action_kind__Druck"] == "print_confirmed"
    assert row.sku in view._print_confirmed_skus  # noqa: SLF001
    assert len(view._direct_product_print_handles) == 1  # noqa: SLF001
    assert started.wait(timeout=1)
    release.set()
    qtbot.waitUntil(lambda: not view._direct_product_print_handles, timeout=2000)  # noqa: SLF001


def test_products_ready_print_action_right_click_opens_settings(
    qtbot: object,
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(ProductsView, "_load_sync_sources", lambda self, *args, **kwargs: None)
    view = ProductsView(Container(AppConfig()))
    qtbot.addWidget(view)
    view.show()
    row = ProductRow(
        sku="XW-RIGHT",
        name="Druckbereit",
        category="Kat",
        on_hand=1,
        price_eur="12.00",
        wix_id="w-right",
        sevdesk_id="s-right",
        print_file_path="ready.pdf",
        print_profile_id="noten_a5",
        print_plan=[],
    )
    view._all_rows = [row]  # noqa: SLF001
    sync_row_type = __import__("xw_office.ui.modules.products.view", fromlist=["_SyncRow"])._SyncRow
    view._sync_rows = [  # noqa: SLF001
        sync_row_type(
            sku=row.sku,
            name=row.name,
            wix_id=row.wix_id,
            sevdesk_id=row.sevdesk_id,
            local_present=True,
            wix_present=True,
            sevdesk_present=True,
            local_stock=1,
            wix_stock=1,
            sevdesk_stock=1,
            local_brand="",
            wix_brand="",
            local_price="12.00",
            wix_price="12.00",
            sevdesk_price="12.00",
            status="sauber verknuepft",
            can_create_sevdesk=False,
        )
    ]
    view._populate_sync_table(view._sync_rows)  # noqa: SLF001
    opened: list[str] = []
    printed: list[str] = []
    monkeypatch.setattr(view, "_manage_product_print_config", lambda sku: opened.append(sku))
    monkeypatch.setattr(view, "_print_product_from_table", lambda sku: printed.append(sku))
    model = view._sync_table.model()  # noqa: SLF001
    assert model is not None
    index = model.index(0, 10)
    rect = view._sync_table.visualRect(index)  # noqa: SLF001

    qtbot.mouseClick(
        view._sync_table.viewport(),  # noqa: SLF001
        Qt.MouseButton.RightButton,
        pos=rect.center(),
    )

    assert opened == ["XW-RIGHT"]
    assert printed == []


def test_products_view_refreshes_stale_row_through_canonical_print_resolver(
    qtbot: object,
    monkeypatch: object,
    tmp_path: object,
) -> None:
    monkeypatch.setattr(ProductsView, "_load_sync_sources", lambda self, *args, **kwargs: None)
    pdf_path = tmp_path / "canonical.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    class CatalogStub:
        def resolve_product_title(self, _sku: str, title: str) -> str:
            return title

        def resolve_print_config(self, _sku: str, *, title: str = "") -> dict[str, object]:
            return {
                "path": str(pdf_path),
                "profile_id": "",
                "print_plan": [{"range": "Alle Seiten", "profile_id": "noten_a5"}],
            }

        def resolve_sku(self, sku: str) -> Product:
            return Product(id="canonical", sku=sku, name="Canonical")

    container = Container(AppConfig())
    container.register(ProductCatalogService, lambda _c: CatalogStub())  # type: ignore[return-value]
    view = ProductsView(container)
    qtbot.addWidget(view)
    stale_row = ProductRow(
        sku="XW-010",
        name="Vielen Dank für die Blumen",
        category="",
        on_hand=0,
        price_eur="",
        wix_id="",
        sevdesk_id="",
        print_file_path="",
        print_profile_id="",
        print_plan=[],
    )

    piece = view._piece_from_product_row(stale_row)  # noqa: SLF001

    assert piece.print_file_path == pdf_path
    assert piece.print_plan == [{"range": "Alle Seiten", "profile_id": "noten_a5"}]
    assert piece.has_direct_print_config is True


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
