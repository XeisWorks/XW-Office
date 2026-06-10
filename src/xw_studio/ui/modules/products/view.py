"""Produkte / Inventar module — Inventar + Wix-Abgleich."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.inventory import InventoryService, ProductRow
from xw_studio.services.draft_invoice.service import DraftInvoiceService, ProductIssueDecision
from xw_studio.services.products.brand_service import ProductBrandService
from xw_studio.services.products.field_bulk_service import ProductFieldBulkService
from xw_studio.services.sevdesk.part_client import PartClient, SevdeskPart
from xw_studio.services.wix.client import WixProduct, WixProductsClient
from xw_studio.ui.modules.products.bulk_field_dialog import BulkFieldEditorDialog
from xw_studio.ui.modules.rechnungen.product_preflight_dialog import ProductPreflightDialog
from xw_studio.ui.widgets.search_bar import SearchBar

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_INV_HEADERS = ["SKU", "Name", "Kategorie", "Brand", "Bestand", "Preis EUR", "Wix-ID", "sevDesk-ID"]
_WIX_HEADERS = ["SKU", "Name", "Brand", "Preis", "Sichtbar", "Bestand", "Wix-ID", "Status"]
_SYNC_HEADERS = [
    "SKU",
    "Name",
    "Status",
    "Konflikt",
    "Brand",
    "Preis",
    "Bestand",
    "Wix-ID",
    "sevDesk-ID",
    "Aktion",
]

_ICONS_DIR = Path(__file__).resolve().parents[5] / "icons"


@dataclass(frozen=True)
class _SyncRow:
    sku: str
    name: str
    wix_id: str
    sevdesk_id: str
    local_present: bool
    wix_present: bool
    sevdesk_present: bool
    local_stock: int
    wix_stock: int | None
    sevdesk_stock: int | None
    local_brand: str
    wix_brand: str
    local_price: str
    wix_price: str
    sevdesk_price: str
    status: str
    can_create_sevdesk: bool


class ProductsView(QWidget):
    """Inventory + Wix sync — tabbed product module."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._all_rows: list[ProductRow] = []
        self._wix_rows: list[WixProduct] = []
        self._sevdesk_rows: list[SevdeskPart] = []
        self._sync_rows: list[_SyncRow] = []
        self._inv_worker: BackgroundWorker | None = None
        self._wix_worker: BackgroundWorker | None = None
        self._sevdesk_worker: BackgroundWorker | None = None
        self._save_worker: BackgroundWorker | None = None
        self._sync_filter_text: str = ""
        self._sync_filter_status: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        root.addWidget(self._build_sync_tab())

        self._load_sync_sources()

    # ==================================================================
    # Inventar tab
    # ==================================================================

    def _build_inventory_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self._inv_status_lbl = QLabel("Produkte werden geladen...")
        self._inv_status_lbl.setObjectName("productsStatusLabel")
        bar.addWidget(self._inv_status_lbl)
        bar.addStretch()
        self._inv_fields_btn = QPushButton("Felder massenhaft ändern")
        self._inv_fields_btn.clicked.connect(self._bulk_edit_fields)
        self._inv_fields_btn.setEnabled(False)
        bar.addWidget(self._inv_fields_btn)
        self._inv_brand_btn = QPushButton("Brand fuer Auswahl setzen")
        self._inv_brand_btn.clicked.connect(self._bulk_set_inventory_brand)
        self._inv_brand_btn.setEnabled(False)
        bar.addWidget(self._inv_brand_btn)
        self._inv_refresh_btn = QPushButton("Aktualisieren")
        self._inv_refresh_btn.clicked.connect(self._load_inventory)
        bar.addWidget(self._inv_refresh_btn)
        lay.addLayout(bar)

        self._inv_search = SearchBar("Produkte filtern (mind. 3 Zeichen)…")
        self._inv_search.setPlaceholderText("Produkte filtern (SKU, Name, Kategorie)...")
        self._inv_search.search_changed.connect(self._apply_inv_filter)
        self._inv_search.set_suggestion_provider(self._inv_search_suggestions)
        lay.addWidget(self._inv_search)

        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("Kategorie:"))
        self._inv_category_combo = QComboBox()
        self._inv_category_combo.addItem("Alle Kategorien", "")
        self._inv_category_combo.currentIndexChanged.connect(self._apply_inv_category_filter)
        cat_row.addWidget(self._inv_category_combo, stretch=1)
        lay.addLayout(cat_row)

        self._inv_table = QTableWidget(0, len(_INV_HEADERS))
        self._inv_table.setHorizontalHeaderLabels(_INV_HEADERS)
        self._inv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._inv_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._inv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._inv_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._inv_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._inv_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self._inv_table)

        footer = QLabel("Produktdaten aus DB (JSON-Key: inventory.products). Eintragen unter Einstellungen.")
        footer.setWordWrap(True)
        footer.setObjectName("infoLabel")
        lay.addWidget(footer)
        return page

    def _load_inventory(self) -> None:
        svc: InventoryService = self._container.resolve(InventoryService)
        self._inv_refresh_btn.setEnabled(False)
        self._inv_status_lbl.setText("Laden...")

        def job() -> list[ProductRow]:
            return svc.list_products()

        self._inv_worker = BackgroundWorker(job)
        self._inv_worker.signals.result.connect(self._on_inv_loaded)
        self._inv_worker.signals.error.connect(self._on_inv_error)
        self._inv_worker.start()

    def _on_inv_loaded(self, rows: object) -> None:
        self._inv_refresh_btn.setEnabled(True)
        if not isinstance(rows, list):
            return
        self._all_rows = rows  # type: ignore[assignment]
        self._inv_brand_btn.setEnabled(bool(self._all_rows))
        self._inv_fields_btn.setEnabled(bool(self._all_rows))
        self._refresh_inv_category_options()
        if not self._all_rows:
            self._inv_status_lbl.setText("Keine Produkte in DB — Einstellungen > inventory.products")
        else:
            self._inv_status_lbl.setText(f"{len(self._all_rows)} Produkte geladen")
        self._inv_search.refresh_suggestions()
        self._apply_inv_filters()

    def _on_inv_error(self, exc: BaseException) -> None:
        self._inv_refresh_btn.setEnabled(True)
        self._inv_status_lbl.setText(f"Fehler: {exc}")
        logger.exception("ProductsView inv load failed: %s", exc)

    def _populate_inv(self, rows: list[ProductRow]) -> None:
        tbl = self._inv_table
        tbl.setRowCount(0)
        for prod in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(prod.sku))
            tbl.setItem(r, 1, QTableWidgetItem(prod.name))
            tbl.setItem(r, 2, QTableWidgetItem(prod.category))
            tbl.setItem(r, 3, QTableWidgetItem(prod.brand_name))
            stock_item = QTableWidgetItem(str(prod.on_hand))
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(r, 4, stock_item)
            price_item = QTableWidgetItem(prod.price_eur)
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tbl.setItem(r, 5, price_item)
            tbl.setItem(r, 6, QTableWidgetItem(prod.wix_id))
            tbl.setItem(r, 7, QTableWidgetItem(prod.sevdesk_id))
        tbl.resizeColumnToContents(0)
        for col in (3, 4, 5, 6, 7):
            tbl.resizeColumnToContents(col)

    def _apply_inv_filter(self, text: str) -> None:
        self._inv_filter_text = text.lower()
        self._apply_inv_filters()

    def _apply_inv_category_filter(self) -> None:
        if self._inv_category_combo is None:
            self._inv_filter_category = ""
        else:
            self._inv_filter_category = str(self._inv_category_combo.currentData() or "").strip().lower()
        self._apply_inv_filters()

    def _apply_inv_filters(self) -> None:
        needle = self._inv_filter_text
        category_filter = self._inv_filter_category
        filtered = [
            p for p in self._all_rows
            if (
                not category_filter
                or p.category.lower().strip() == category_filter
            )
            and (
                not needle
                or needle in p.sku.lower()
                or needle in p.name.lower()
                or needle in p.category.lower()
                or needle in (p.brand_name or "").lower()
            )
        ]
        self._populate_inv(filtered)

    def _refresh_inv_category_options(self) -> None:
        if self._inv_category_combo is None:
            return
        categories = sorted({(row.category or "").strip() for row in self._all_rows if (row.category or "").strip()})
        current = self._inv_filter_category
        self._inv_category_combo.blockSignals(True)
        self._inv_category_combo.clear()
        self._inv_category_combo.addItem("Alle Kategorien", "")
        for category in categories:
            self._inv_category_combo.addItem(category, category)
        idx = self._inv_category_combo.findData(current)
        self._inv_category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._inv_category_combo.blockSignals(False)

    # ==================================================================
    # Wix-Abgleich tab
    # ==================================================================

    def _build_wix_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self._wix_status_lbl = QLabel("Wix-Produkte noch nicht geladen.")
        bar.addWidget(self._wix_status_lbl)
        bar.addStretch()
        self._wix_fields_btn = QPushButton("Felder fuer Auswahl aendern")
        self._wix_fields_btn.clicked.connect(self._bulk_edit_wix_fields)
        self._wix_fields_btn.setEnabled(False)
        bar.addWidget(self._wix_fields_btn)
        self._wix_load_btn = QPushButton("Wix-Produkte laden")
        self._wix_load_btn.clicked.connect(self._load_wix)
        bar.addWidget(self._wix_load_btn)
        lay.addLayout(bar)

        self._wix_search = SearchBar("Wix-Produkte filtern (mind. 3 Zeichen)…")
        self._wix_search.setPlaceholderText("Filtern (SKU, Name)...")
        self._wix_search.search_changed.connect(self._apply_wix_filter)
        self._wix_search.set_suggestion_provider(self._wix_search_suggestions)
        lay.addWidget(self._wix_search)

        self._wix_table = QTableWidget(0, len(_WIX_HEADERS))
        self._wix_table.setHorizontalHeaderLabels(_WIX_HEADERS)
        self._wix_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._wix_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._wix_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._wix_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._wix_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self._wix_table, stretch=2)

        # SKU-Overlap summary
        self._overlap_lbl = QLabel("")
        self._overlap_lbl.setObjectName("infoLabel")
        self._overlap_lbl.setWordWrap(True)
        lay.addWidget(self._overlap_lbl)
        return page

    def _load_wix(self) -> None:
        client: WixProductsClient = self._container.resolve(WixProductsClient)
        if not client.has_credentials():
            QMessageBox.warning(
                self,
                "Wix-Abgleich",
                "Kein WIX_API_KEY oder WIX_SITE_ID konfiguriert.\n"
                "Bitte unter Einstellungen > Token-Verwaltung eintragen.",
            )
            return
        self._wix_load_btn.setEnabled(False)
        self._wix_status_lbl.setText("Lade Wix-Produkte...")

        def job() -> list[WixProduct]:
            return client.list_products()

        self._wix_worker = BackgroundWorker(job)
        self._wix_worker.signals.result.connect(self._on_wix_loaded)
        self._wix_worker.signals.error.connect(self._on_wix_error)
        self._wix_worker.start()

    def _on_wix_loaded(self, rows: object) -> None:
        self._wix_load_btn.setEnabled(True)
        if not isinstance(rows, list):
            return
        self._wix_rows = rows  # type: ignore[assignment]
        self._wix_fields_btn.setEnabled(bool(self._wix_rows))
        self._wix_status_lbl.setText(f"{len(self._wix_rows)} Wix-Produkte geladen")
        self._wix_search.refresh_suggestions()
        self._populate_wix(self._wix_rows)
        self._compute_overlap()

    def _on_wix_error(self, exc: BaseException) -> None:
        self._wix_load_btn.setEnabled(True)
        self._wix_fields_btn.setEnabled(False)
        self._wix_status_lbl.setText(f"Fehler: {exc}")
        logger.exception("Wix load failed: %s", exc)
        QMessageBox.warning(self, "Wix-Abgleich", str(exc))



    def _populate_wix(self, rows: list[WixProduct]) -> None:
        tbl = self._wix_table
        tbl.setRowCount(0)
        inv_skus = {p.sku for p in self._all_rows if p.sku}
        for prod in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(prod.sku))
            tbl.setItem(r, 1, QTableWidgetItem(prod.name))
            tbl.setItem(r, 2, QTableWidgetItem(prod.brand_name))
            price_item = QTableWidgetItem(prod.price)
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tbl.setItem(r, 3, price_item)
            vis_item = QTableWidgetItem("ja" if prod.visible else "nein")
            vis_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(r, 4, vis_item)
            qty_item = QTableWidgetItem(str(prod.inventory_quantity))
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(r, 5, qty_item)
            tbl.setItem(r, 6, QTableWidgetItem(prod.id))
            # Status: matched in local DB?
            matched = prod.sku in inv_skus if prod.sku else False
            status_item = QTableWidgetItem("verknuepft" if matched else "nur Wix")
            status_item.setForeground(
                Qt.GlobalColor.green if matched else Qt.GlobalColor.yellow
            )
            tbl.setItem(r, 7, status_item)
        for col in (0, 2, 4, 5, 7):
            tbl.resizeColumnToContents(col)

    def _apply_wix_filter(self, text: str) -> None:
        needle = text.lower()
        filtered = [
            p for p in self._wix_rows
            if needle in p.sku.lower() or needle in p.name.lower() or needle in (p.brand_name or "").lower()
        ]
        self._populate_wix(filtered)

    def _inv_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 3:
            return []
        items: list[str] = []
        for row in self._all_rows:
            hay = f"{row.sku} {row.name} {row.category} {row.brand_name}".lower()
            if q in hay:
                items.append(f"{row.sku} - {row.name}")
        return items

    def _wix_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 3:
            return []
        items: list[str] = []
        for row in self._wix_rows:
            hay = f"{row.sku} {row.name} {row.brand_name}".lower()
            if q in hay:
                items.append(f"{row.sku} - {row.name}")
        return items

    def _compute_overlap(self) -> None:
        inv_skus = {p.sku for p in self._all_rows if p.sku}
        wix_skus = {p.sku for p in self._wix_rows if p.sku}
        matched = inv_skus & wix_skus
        only_wix = wix_skus - inv_skus
        only_inv = inv_skus - wix_skus
        self._overlap_lbl.setText(
            f"Abgleich: {len(matched)} verknuepft | "
            f"{len(only_wix)} nur in Wix | "
            f"{len(only_inv)} nur in lokalem Inventar"
        )

    # ==================================================================
    # Sync tab (local / Wix / sevDesk)
    # ==================================================================

    def _build_sync_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self._sync_status_lbl = QLabel("Noch kein Sync-Vergleich geladen.")
        bar.addWidget(self._sync_status_lbl)
        bar.addStretch()
        self._sync_load_btn = QPushButton("Alle Quellen laden")
        self._sync_load_btn.clicked.connect(self._load_sync_sources)
        bar.addWidget(self._sync_load_btn)
        self._sync_fields_btn = QPushButton("Felder fuer Auswahl aendern")
        self._sync_fields_btn.clicked.connect(self._bulk_edit_fields)
        self._sync_fields_btn.setEnabled(False)
        bar.addWidget(self._sync_fields_btn)
        self._sync_brand_btn = QPushButton("Brand fuer Auswahl setzen")
        self._sync_brand_btn.clicked.connect(self._bulk_set_inventory_brand)
        self._sync_brand_btn.setEnabled(False)
        bar.addWidget(self._sync_brand_btn)
        self._legacy_import_btn = QPushButton("Legacy-Druckdaten importieren")
        self._legacy_import_btn.clicked.connect(self._import_legacy_print_data)
        bar.addWidget(self._legacy_import_btn)
        self._sync_apply_btn = QPushButton("Wix -> Lokal uebernehmen")
        self._sync_apply_btn.clicked.connect(self._apply_wix_to_local)
        self._sync_apply_btn.setEnabled(False)
        bar.addWidget(self._sync_apply_btn)
        lay.addLayout(bar)

        filter_row = QHBoxLayout()
        self._sync_search = SearchBar("Produkte filtern (SKU, Name, Brand, Status)...")
        self._sync_search.setPlaceholderText("Produkte filtern (SKU, Name, Brand, Status)...")
        self._sync_search.search_changed.connect(self._apply_sync_filter)
        filter_row.addWidget(self._sync_search, stretch=1)
        filter_row.addWidget(QLabel("Status:"))
        self._sync_status_combo = QComboBox()
        self._sync_status_combo.addItem("Alle", "")
        self._sync_status_combo.addItems([
            "sauber verknuepft",
            "nur Wix",
            "nur sevDesk",
            "nur lokal DB",
            "Wix + lokal, nicht in sevDesk",
            "Wix + sevDesk, nicht lokal",
            "lokal + sevDesk, nicht in Wix",
            "Konflikt",
        ])
        self._sync_status_combo.currentIndexChanged.connect(self._apply_sync_status_filter)
        filter_row.addWidget(self._sync_status_combo)
        lay.addLayout(filter_row)

        self._sync_table = QTableWidget(0, len(_SYNC_HEADERS))
        self._sync_table.setHorizontalHeaderLabels(_SYNC_HEADERS)
        self._sync_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._sync_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._sync_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._sync_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._sync_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._sync_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self._sync_table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)
        self._sync_table.setColumnWidth(2, 86)
        self._sync_table.setColumnWidth(3, 72)
        self._sync_table.setColumnWidth(5, 92)
        self._sync_table.setColumnWidth(6, 76)
        self._sync_table.setColumnWidth(9, 44)
        for index, tooltip in {
            2: "Systemstatus: lokal, Wix, sevDesk",
            3: "Konflikte bei Preis oder Bestand",
            5: "Preis im Format € 0,00",
            9: "Aktion fuer nur-Wix-Produkte",
        }.items():
            header_item = self._sync_table.horizontalHeaderItem(index)
            if header_item is not None:
                header_item.setToolTip(tooltip)
        self._sync_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._sync_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._sync_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lay.addWidget(self._sync_table, stretch=1)

        tip = QLabel(
            "Eine Liste fuer Lokal-DB, Wix und sevDesk. Der Status zeigt, ob ein Produkt sauber verknuepft ist, "
            "nur in einem System vorkommt oder Datenkonflikte hat."
        )
        tip.setWordWrap(True)
        tip.setObjectName("infoLabel")
        lay.addWidget(tip)

        plans_group = QGroupBox("Druckplaene (JSON)")
        plans_lay = QVBoxLayout(plans_group)
        self._plans_editor = QPlainTextEdit()
        self._plans_editor.setPlaceholderText(
            '[{"sku": "XW-4-001", "min_qty": 1, "target_qty": 3, "pdf": "plans/xw-4-001.pdf"}]'
        )
        self._plans_editor.setMinimumHeight(130)
        plans_lay.addWidget(self._plans_editor)
        plans_btns = QHBoxLayout()
        load_plans_btn = QPushButton("Druckplaene laden")
        load_plans_btn.clicked.connect(self._load_print_plans)
        plans_btns.addWidget(load_plans_btn)
        save_plans_btn = QPushButton("Druckplaene speichern")
        save_plans_btn.clicked.connect(self._save_print_plans)
        plans_btns.addWidget(save_plans_btn)
        plans_btns.addStretch()
        plans_lay.addLayout(plans_btns)
        lay.addWidget(plans_group)
        return page

    def _load_sync_sources(self) -> None:
        self._sync_load_btn.setEnabled(False)
        self._sync_apply_btn.setEnabled(False)
        self._sync_status_lbl.setText("Lade lokale Produkte, Wix und sevDesk...")

        def job() -> tuple[list[ProductRow], list[WixProduct], list[SevdeskPart]]:
            inv: InventoryService = self._container.resolve(InventoryService)
            wix_client: WixProductsClient = self._container.resolve(WixProductsClient)
            part_client: PartClient = self._container.resolve(PartClient)

            local = inv.list_products()
            wix = wix_client.list_products()
            sevdesk: list[SevdeskPart] = []
            try:
                sevdesk = part_client.list_parts()
            except Exception as exc:  # noqa: BLE001
                logger.warning("sevDesk products not available for sync: %s", exc)
            return (local, wix, sevdesk)

        self._sevdesk_worker = BackgroundWorker(job)
        self._sevdesk_worker.signals.result.connect(self._on_sync_sources_loaded)
        self._sevdesk_worker.signals.error.connect(self._on_sync_sources_error)
        self._sevdesk_worker.start()

    def _on_sync_sources_loaded(self, payload: object) -> None:
        self._sync_load_btn.setEnabled(True)
        if not isinstance(payload, tuple) or len(payload) != 3:
            return
        local_rows, wix_rows, sevdesk_rows = payload
        if not isinstance(local_rows, list) or not isinstance(wix_rows, list) or not isinstance(sevdesk_rows, list):
            return
        self._all_rows = [r for r in local_rows if isinstance(r, ProductRow)]
        self._wix_rows = [r for r in wix_rows if isinstance(r, WixProduct)]
        self._sevdesk_rows = [r for r in sevdesk_rows if isinstance(r, SevdeskPart)]

        self._sync_rows = self._build_sync_rows()
        self._sync_fields_btn.setEnabled(bool(self._sync_rows))
        self._sync_brand_btn.setEnabled(bool(self._sync_rows))
        self._sync_search.refresh_suggestions()
        self._apply_sync_filters()
        conflicts = sum(1 for row in self._sync_rows if row.status != "sauber verknuepft")
        self._sync_status_lbl.setText(
            f"Sync-Vergleich geladen: {len(self._sync_rows)} SKU, Konflikte: {conflicts}"
        )
        self._sync_apply_btn.setEnabled(bool(self._wix_rows))

    def _on_sync_sources_error(self, exc: BaseException) -> None:
        self._sync_load_btn.setEnabled(True)
        self._sync_fields_btn.setEnabled(False)
        self._sync_brand_btn.setEnabled(False)
        self._sync_apply_btn.setEnabled(False)
        self._sync_status_lbl.setText(f"Fehler: {exc}")
        logger.exception("Sync source load failed: %s", exc)

    def _build_sync_rows(self) -> list[_SyncRow]:
        local_by_sku = {row.sku: row for row in self._all_rows if row.sku}
        wix_by_sku = {row.sku: row for row in self._wix_rows if row.sku}
        sevdesk_by_sku = {row.sku: row for row in self._sevdesk_rows if row.sku}
        all_skus = sorted(set(local_by_sku) | set(wix_by_sku) | set(sevdesk_by_sku))

        rows: list[_SyncRow] = []
        for sku in all_skus:
            local = local_by_sku.get(sku)
            wix = wix_by_sku.get(sku)
            sevdesk = sevdesk_by_sku.get(sku)

            local_stock = local.on_hand if local is not None else 0
            wix_stock = wix.inventory_quantity if wix is not None else None
            sevdesk_stock = sevdesk.stock_qty if sevdesk is not None else None

            local_price = local.price_eur if local is not None else ""
            wix_price = wix.price if wix is not None else ""
            sevdesk_price = sevdesk.price_eur if sevdesk is not None else ""
            local_brand = local.brand_name if local is not None else ""
            wix_brand = wix.brand_name if wix is not None else ""
            name = (
                (local.name if local is not None else "")
                or (wix.name if wix is not None else "")
                or (sevdesk.name if sevdesk is not None else "")
            )

            has_local = local is not None
            has_wix = wix is not None
            has_sevdesk = sevdesk is not None
            if has_wix and not has_sevdesk and not has_local:
                status = "nur Wix"
            elif has_sevdesk and not has_wix and not has_local:
                status = "nur sevDesk"
            elif has_local and not has_wix and not has_sevdesk:
                status = "nur lokal DB"
            elif has_wix and has_local and not has_sevdesk:
                status = "Wix + lokal, nicht in sevDesk"
            elif has_wix and has_sevdesk and not has_local:
                status = "Wix + sevDesk, nicht lokal"
            elif has_local and has_sevdesk and not has_wix:
                status = "lokal + sevDesk, nicht in Wix"
            else:
                diffs: list[str] = []
                if wix is not None and local is not None and wix_stock != local_stock:
                    diffs.append("Bestand Wix")
                if sevdesk is not None and local is not None and sevdesk_stock != local_stock:
                    diffs.append("Bestand sevDesk")
                if wix is not None and local is not None and (wix_price or "") != (local_price or ""):
                    diffs.append("Preis Wix")
                if sevdesk is not None and local is not None and (sevdesk_price or "") != (local_price or ""):
                    diffs.append("Preis sevDesk")
                status = "sauber verknuepft" if not diffs else f"Konflikt: {', '.join(diffs)}"

            rows.append(
                _SyncRow(
                    sku=sku,
                    name=name,
                    wix_id=wix.id if wix is not None else (local.wix_id if local is not None else ""),
                    sevdesk_id=sevdesk.id if sevdesk is not None else (local.sevdesk_id if local is not None else ""),
                    local_present=has_local,
                    wix_present=has_wix,
                    sevdesk_present=has_sevdesk,
                    local_stock=local_stock,
                    wix_stock=wix_stock,
                    sevdesk_stock=sevdesk_stock,
                    local_brand=local_brand,
                    wix_brand=wix_brand,
                    local_price=local_price,
                    wix_price=wix_price,
                    sevdesk_price=sevdesk_price,
                    status=status,
                    can_create_sevdesk=has_wix and not has_sevdesk,
                )
            )
        return rows

    def _populate_sync_table(self, rows: list[_SyncRow]) -> None:
        tbl = self._sync_table
        tbl.setRowCount(0)
        for row in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(row.sku))
            tbl.setItem(r, 1, QTableWidgetItem(row.name))
            tbl.setItem(r, 2, QTableWidgetItem(""))
            tbl.setCellWidget(r, 2, self._build_status_icons_widget(row))
            tbl.setItem(r, 3, QTableWidgetItem(""))
            tbl.setCellWidget(r, 3, self._build_conflict_icons_widget(row))
            tbl.setItem(r, 4, QTableWidgetItem(row.local_brand or row.wix_brand))
            price_item = QTableWidgetItem(self._format_eur(row.local_price or row.wix_price or row.sevdesk_price))
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tbl.setItem(r, 5, price_item)
            stock_value = row.local_stock if row.local_present else (row.wix_stock if row.wix_stock is not None else row.sevdesk_stock)
            stock_item = QTableWidgetItem("" if stock_value is None else str(stock_value))
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(r, 6, stock_item)
            tbl.setItem(r, 7, QTableWidgetItem(row.wix_id))
            tbl.setItem(r, 8, QTableWidgetItem(row.sevdesk_id))
            if row.can_create_sevdesk:
                btn = QPushButton("")
                btn.setIcon(QIcon(str(_ICONS_DIR / "createInSevdesk.png")))
                btn.setIconSize(QSize(18, 18))
                btn.setFixedSize(28, 24)
                btn.setToolTip("In sevDesk anlegen")
                btn.setFlat(True)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _checked=False, sku=row.sku: self._create_selected_wix_product_in_sevdesk(sku))
                tbl.setCellWidget(r, 9, btn)
            else:
                tbl.setItem(r, 9, QTableWidgetItem(""))
        for col in (2, 3, 4, 5, 6, 7, 8, 9):
            tbl.resizeColumnToContents(col)

    def _build_status_icons_widget(self, row: _SyncRow) -> QWidget:
        widget = QWidget(self._sync_table)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(self._icon_label("cloud.png", QColor("#16a34a") if row.local_present else QColor("#dc2626"), tooltip="Lokal DB"))
        layout.addWidget(self._icon_label("wix.png", QColor("#16a34a") if row.wix_present else QColor("#dc2626"), tooltip="Wix"))
        layout.addWidget(self._icon_label("sevdesk.png", QColor("#16a34a") if row.sevdesk_present else QColor("#dc2626"), tooltip="sevDesk"))
        layout.addStretch(1)
        return widget

    def _build_conflict_icons_widget(self, row: _SyncRow) -> QWidget:
        widget = QWidget(self._sync_table)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        for file_name, tooltip in self._conflict_icon_specs(row):
            layout.addWidget(self._icon_label(file_name, QColor("#f59e0b"), tooltip=tooltip))
        layout.addStretch(1)
        return widget

    def _conflict_icon_specs(self, row: _SyncRow) -> list[tuple[str, str]]:
        labels: list[tuple[str, str]] = []
        if row.local_present and row.wix_present and (row.local_price or "") != (row.wix_price or ""):
            labels.append(("priceNotSynced.png", "Preis nicht mit Wix synchron"))
        if row.local_present and row.sevdesk_present and (row.local_price or "") != (row.sevdesk_price or ""):
            labels.append(("priceNotSynced.png", "Preis nicht mit sevDesk synchron"))
        if row.local_present and row.wix_present and row.wix_stock != row.local_stock:
            labels.append(("cloud.png", "Bestand nicht mit Wix synchron"))
        if row.local_present and row.sevdesk_present and row.sevdesk_stock != row.local_stock:
            labels.append(("cloud.png", "Bestand nicht mit sevDesk synchron"))
        return labels

    def _icon_label(self, file_name: str, color: QColor, *, tooltip: str) -> QLabel:
        label = QLabel()
        label.setPixmap(self._tinted_icon(file_name, color))
        label.setToolTip(tooltip)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _tinted_icon(self, file_name: str, color: QColor, *, size: int = 16) -> QPixmap:
        pix = QPixmap(str(_ICONS_DIR / file_name))
        if pix.isNull():
            return QPixmap()
        scaled = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        image = QImage(scaled.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.drawPixmap(0, 0, scaled)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(image.rect(), color)
        painter.end()
        return QPixmap.fromImage(image)

    @staticmethod
    def _format_eur(value: str) -> str:
        text = str(value or "").strip().replace("€", "").replace(" ", "").replace(",", ".")
        if not text:
            return ""
        try:
            amount = float(text)
        except ValueError:
            return str(value)
        formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"€ {formatted}"

    def _apply_sync_filter(self, text: str) -> None:
        self._sync_filter_text = text.lower().strip()
        self._apply_sync_filters()

    def _apply_sync_status_filter(self) -> None:
        self._sync_filter_status = str(self._sync_status_combo.currentText() or "").strip().lower()
        if self._sync_filter_status == "alle":
            self._sync_filter_status = ""
        self._apply_sync_filters()

    def _apply_sync_filters(self) -> None:
        needle = self._sync_filter_text
        status_filter = self._sync_filter_status
        filtered: list[_SyncRow] = []
        for row in self._sync_rows:
            hay = f"{row.sku} {row.name} {row.local_brand} {row.wix_brand} {row.status}".lower()
            if needle and needle not in hay:
                continue
            if status_filter and status_filter not in row.status.lower():
                continue
            filtered.append(row)
        self._populate_sync_table(filtered)

    def _selected_product_skus(self) -> list[str]:
        selected_rows = sorted({item.row() for item in self._sync_table.selectedItems()})
        skus: list[str] = []
        for row in selected_rows:
            sku_item = self._sync_table.item(row, 0)
            if sku_item is None:
                continue
            sku = sku_item.text().strip()
            if sku:
                skus.append(sku)
        return skus

    def _apply_wix_to_local(self) -> None:
        if not self._wix_rows:
            QMessageBox.information(self, "Produkte", "Bitte zuerst Wix-Daten laden.")
            return
        inv: InventoryService = self._container.resolve(InventoryService)

        local_by_sku = {row.sku: row for row in self._all_rows if row.sku}
        merged = dict(local_by_sku)
        changed = 0
        for wix in self._wix_rows:
            if not wix.sku:
                continue
            current = merged.get(wix.sku)
            if current is None:
                merged[wix.sku] = ProductRow(
                    sku=wix.sku,
                    name=wix.name,
                    category="",
                    on_hand=max(0, int(wix.inventory_quantity)),
                    price_eur=wix.price,
                    brand_name=wix.brand_name,
                    brand_id=wix.brand_id,
                    wix_id=wix.id,
                    sevdesk_id="",
                    print_file_path="",
                    print_profile_id="",
                    print_plan=[],
                    title_print_configs={},
                )
                changed += 1
                continue
            updated = ProductRow(
                sku=current.sku,
                name=current.name or wix.name,
                category=current.category,
                on_hand=max(0, int(wix.inventory_quantity)),
                price_eur=wix.price or current.price_eur,
                brand_name=wix.brand_name or current.brand_name,
                brand_id=wix.brand_id or current.brand_id,
                wix_id=wix.id or current.wix_id,
                sevdesk_id=current.sevdesk_id,
                print_file_path=current.print_file_path,
                print_profile_id=current.print_profile_id,
                print_plan=list(current.print_plan or []),
                title_print_configs=dict(current.title_print_configs or {}),
            )
            if updated != current:
                merged[wix.sku] = updated
                changed += 1

        if changed == 0:
            QMessageBox.information(self, "Produkte", "Keine Aenderungen aus Wix zu uebernehmen.")
            return

        to_save = sorted(merged.values(), key=lambda row: row.sku)
        self._sync_apply_btn.setEnabled(False)
        self._sync_status_lbl.setText("Speichere Wix->Lokal Abgleich...")

        def job() -> int:
            inv.save_products(to_save)
            return changed

        self._save_worker = BackgroundWorker(job)
        self._save_worker.signals.result.connect(self._on_apply_done)
        self._save_worker.signals.error.connect(self._on_apply_error)
        self._save_worker.start()

    def _on_apply_done(self, changed: object) -> None:
        self._sync_apply_btn.setEnabled(True)
        count = int(changed) if isinstance(changed, int) else 0
        self._sync_status_lbl.setText(f"Wix->Lokal gespeichert: {count} Produkte aktualisiert")
        try:
            from xw_studio.services.products.catalog import ProductCatalogService

            self._container.resolve(ProductCatalogService).reload_from_settings()
        except Exception:
            pass
        QMessageBox.information(self, "Produkte", f"{count} Produkte wurden lokal aktualisiert.")
        self._load_sync_sources()

    def _on_apply_error(self, exc: BaseException) -> None:
        self._sync_apply_btn.setEnabled(True)
        self._sync_status_lbl.setText(f"Fehler: {exc}")
        QMessageBox.warning(self, "Produkte", str(exc))

    def _import_legacy_print_data(self) -> None:
        inv: InventoryService = self._container.resolve(InventoryService)
        self._legacy_import_btn.setEnabled(False)
        self._sync_status_lbl.setText("Importiere Legacy-Druckdaten...")

        def job():
            return inv.import_legacy_print_data()

        self._save_worker = BackgroundWorker(job)
        self._save_worker.signals.result.connect(self._on_legacy_import_done)
        self._save_worker.signals.error.connect(self._on_legacy_import_error)
        self._save_worker.start()

    def _on_legacy_import_done(self, payload: object) -> None:
        self._legacy_import_btn.setEnabled(True)
        report = payload
        if report is None:
            self._sync_status_lbl.setText("Legacy-Import abgeschlossen")
            self._load_sync_sources()
            return
        source_path = str(getattr(report, "source_path", "") or "")
        updated = int(getattr(report, "products_updated", 0) or 0)
        title_count = int(getattr(report, "title_configs_imported", 0) or 0)
        missing = list(getattr(report, "missing_files", []) or [])
        unknown_profiles = list(getattr(report, "unknown_profiles", []) or [])
        self._sync_status_lbl.setText(f"Legacy-Import: {updated} Produkte aktualisiert")
        lines = [
            f"Quelle: {source_path}",
            f"Aktualisierte Produkte: {updated}",
            f"Importierte Titel-Konfigurationen: {title_count}",
        ]
        if unknown_profiles:
            lines.append("")
            lines.append("Unbekannte Profil-IDs:")
            lines.extend(f"- {value}" for value in unknown_profiles[:12])
        if missing:
            lines.append("")
            lines.append("Fehlende PDF-Dateien:")
            lines.extend(f"- {value}" for value in missing[:12])
        try:
            from xw_studio.services.products.catalog import ProductCatalogService

            self._container.resolve(ProductCatalogService).reload_from_settings()
        except Exception:
            pass
        QMessageBox.information(self, "Legacy-Druckdaten", "\n".join(lines))
        self._load_sync_sources()

    def _on_legacy_import_error(self, exc: BaseException) -> None:
        self._legacy_import_btn.setEnabled(True)
        self._sync_status_lbl.setText(f"Fehler: {exc}")
        QMessageBox.warning(self, "Legacy-Druckdaten", str(exc))

    def _load_print_plans(self) -> None:
        inv: InventoryService = self._container.resolve(InventoryService)
        plans = inv.load_print_plans()
        self._plans_editor.setPlainText(json.dumps(plans, ensure_ascii=False, indent=2))

    def _save_print_plans(self) -> None:
        inv: InventoryService = self._container.resolve(InventoryService)
        raw = self._plans_editor.toPlainText().strip() or "[]"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "Druckplaene", f"Ungueltiges JSON: {exc}")
            return
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            QMessageBox.warning(self, "Druckplaene", "Erwartet wird ein JSON-Array aus Objekten.")
            return
        inv.save_print_plans(data)
        QMessageBox.information(self, "Druckplaene", f"{len(data)} Druckplan-Eintraege gespeichert.")

    def _selected_inventory_skus(self) -> list[str]:
        return self._selected_product_skus()

    def _selected_wix_skus(self) -> list[str]:
        return self._selected_product_skus()

    def _run_bulk_field_dialog(self, skus: list[str], *, source_label: str) -> None:
        if not skus:
            QMessageBox.information(
                self,
                "Felder aendern",
                f"Bitte zuerst Produkte in der {source_label}-Tabelle auswaehlen.",
            )
            return

        service: ProductFieldBulkService = self._container.resolve(ProductFieldBulkService)
        dialog = BulkFieldEditorDialog(service, self)
        dialog.set_selected_skus(skus)
        dialog.set_wix_products(self._wix_rows)

        if dialog.exec() != BulkFieldEditorDialog.DialogCode.Accepted:
            return

        field_name, operator, value, sync_wix = dialog.get_field_and_value()
        if not field_name or not operator or not value:
            QMessageBox.warning(self, "Felder aendern", "Bitte alle Felder ausfuellen.")
            return

        try:
            report = service.apply_field_update(
                skus=skus,
                field_name=field_name,
                operator=operator,
                value=value,
                sync_wix=sync_wix,
                wix_products=self._wix_rows,
            )

            fields = service.get_editable_fields()
            field_label = fields.get(field_name).label if field_name in fields else field_name  # type: ignore[union-attr]
            message = (
                f"Feld: {field_label}\n"
                f"Operation: {report.operator}\n"
                f"Wert: {report.value}\n\n"
                f"Geaendert (lokal): {report.changed}\n"
                f"Uebersprungen: {report.skipped}\n"
                f"Fehler: {report.failed}\n"
            )
            if sync_wix:
                message += (
                    f"\nWix versucht: {report.wix_attempted}\n"
                    f"Wix erfolgreich: {report.wix_updated}\n"
                    f"Wix Fehler: {report.wix_failed}"
                )

            QMessageBox.information(self, "Felder aendern - Abgeschlossen", message)
            self._load_sync_sources()
        except ValueError as exc:
            QMessageBox.warning(self, "Felder aendern - Fehler", f"Fehler: {exc}")

    def _bulk_edit_wix_fields(self) -> None:
        self._run_bulk_field_dialog(self._selected_product_skus(), source_label="Produkte")

    def _create_selected_wix_product_in_sevdesk(self, sku: str) -> None:
        normalized_sku = str(sku or "").strip().upper()
        if not normalized_sku:
            return
        wix_product = next((row for row in self._wix_rows if row.sku.strip().upper() == normalized_sku), None)
        if wix_product is None:
            QMessageBox.warning(self, "sevDesk", f"Wix-Produkt fuer SKU {normalized_sku} nicht gefunden.")
            return

        service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
        try:
            plan = service.build_manual_wix_product_plan(
                sku=wix_product.sku,
                wix_name=wix_product.name,
                wix_product_id=wix_product.id,
                wix_description="",
                wix_price_gross=float(wix_product.price) if str(wix_product.price or "").strip() else None,
                is_digital=False,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "sevDesk", str(exc))
            return

        issue = plan.issues[0] if plan.issues else None
        if issue is None:
            QMessageBox.warning(self, "sevDesk", "Produktdialog konnte nicht vorbereitet werden.")
            return

        dialog = ProductPreflightDialog(issue, part_categories=plan.part_categories, parent=self)
        decision = dialog.show_dialog()
        if decision is None:
            decision = ProductIssueDecision(action="skip", draft=issue.draft)
        if decision.action != "create_part":
            return

        try:
            created = service.create_part_from_decision(issue, decision)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "sevDesk", f"Produkt konnte nicht angelegt werden:\n{exc}")
            return

        self._upsert_local_product_from_wix(wix_product, sevdesk_id=created.id)
        QMessageBox.information(
            self,
            "sevDesk",
            f"Produkt [{created.sku}] {created.name} wurde in sevDesk angelegt.",
        )
        self._load_sync_sources()

    def _upsert_local_product_from_wix(self, wix: WixProduct, *, sevdesk_id: str) -> None:
        inv: InventoryService = self._container.resolve(InventoryService)
        local_by_sku = {row.sku: row for row in self._all_rows if row.sku}
        current = local_by_sku.get(wix.sku)
        if current is None:
            local_by_sku[wix.sku] = ProductRow(
                sku=wix.sku,
                name=wix.name,
                category="",
                on_hand=max(0, int(wix.inventory_quantity)),
                price_eur=wix.price,
                brand_name=wix.brand_name,
                brand_id=wix.brand_id,
                wix_id=wix.id,
                sevdesk_id=sevdesk_id,
                print_file_path="",
                print_profile_id="",
                print_plan=[],
                title_print_configs={},
            )
        else:
            local_by_sku[wix.sku] = ProductRow(
                sku=current.sku,
                name=current.name or wix.name,
                category=current.category,
                on_hand=max(0, int(wix.inventory_quantity)),
                price_eur=wix.price or current.price_eur,
                brand_name=wix.brand_name or current.brand_name,
                brand_id=wix.brand_id or current.brand_id,
                wix_id=wix.id or current.wix_id,
                sevdesk_id=sevdesk_id or current.sevdesk_id,
                print_file_path=current.print_file_path,
                print_profile_id=current.print_profile_id,
                print_plan=list(current.print_plan or []),
                title_print_configs=dict(current.title_print_configs or {}),
            )
        inv.save_products(sorted(local_by_sku.values(), key=lambda row: row.sku))

    def _bulk_set_inventory_brand(self) -> None:
        skus = self._selected_inventory_skus()
        if not skus:
            QMessageBox.information(self, "Brand-Update", "Bitte zuerst Produkte in der Inventar-Tabelle auswaehlen.")
            return

        new_brand, ok = QInputDialog.getText(self, "Brand-Update", "Neue Brand (Marke):")
        if not ok:
            return
        target_brand = new_brand.strip()
        if not target_brand:
            QMessageBox.warning(self, "Brand-Update", "Brand darf nicht leer sein.")
            return

        service: ProductBrandService = self._container.resolve(ProductBrandService)
        preview = service.preview_local_brand_update(skus, target_brand)
        if preview.requested == 0:
            QMessageBox.information(self, "Brand-Update", "Keine gueltigen Ziele gefunden.")
            return

        question = (
            f"Ausgewaehlt: {preview.requested}\n"
            f"Wuerden geaendert: {preview.changed}\n"
            f"Uebersprungen: {preview.skipped}\n\n"
            f"Brand setzen auf: {target_brand}\n\n"
            "Aenderung jetzt speichern?"
        )
        if QMessageBox.question(self, "Brand-Update Vorschau", question) != QMessageBox.StandardButton.Yes:
            return

        sync_choice = QMessageBox.question(
            self,
            "Wix Writeback",
            "Soll die Brand zusaetzlich in Wix aktualisiert werden?\n\n"
            "Ja: Lokal + Wix\n"
            "Nein: Nur lokal",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        sync_wix = sync_choice == QMessageBox.StandardButton.Yes

        create_missing_wix_brand = False
        if sync_wix:
            create_choice = QMessageBox.question(
                self,
                "Wix Brand anlegen",
                "Falls die Brand in Wix noch nicht existiert: automatisch anlegen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            create_missing_wix_brand = create_choice == QMessageBox.StandardButton.Yes

        report = service.apply_brand_update(
            skus,
            target_brand,
            sync_wix=sync_wix,
            create_missing_wix_brand=create_missing_wix_brand,
        )
        self._sync_status_lbl.setText(
            f"Brand-Update: geaendert={report.changed}, uebersprungen={report.skipped}, "
            f"wix_ok={report.wix_updated}, wix_fehler={report.wix_failed}"
        )
        QMessageBox.information(
            self,
            "Brand-Update",
            "Brand-Update abgeschlossen.\n"
            f"Geaendert (lokal): {report.changed}\n"
            f"Uebersprungen: {report.skipped}\n"
            f"Wix versucht: {report.wix_attempted}\n"
            f"Wix erfolgreich: {report.wix_updated}\n"
            f"Wix Fehler: {report.wix_failed}\n"
            f"Brand aufgeloest: {'ja' if report.wix_brand_resolved else 'nein'}\n"
            f"Brand neu angelegt: {'ja' if report.wix_brand_created else 'nein'}",
        )
        self._load_sync_sources()

    def _bulk_edit_fields(self) -> None:
        """Open dialog for bulk product field editing."""
        self._run_bulk_field_dialog(self._selected_product_skus(), source_label="Produkte")

