"""Produkte / Inventar module — Inventar + Wix-Abgleich."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
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
    QStyledItemDelegate,
    QStyle,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.inventory import InventoryService, ProductRow
from xw_studio.services.draft_invoice.service import (
    DraftInvoiceService,
    ProductIssueDecision,
    ProductPreflightPlan,
)
from xw_studio.services.products.brand_service import BrandBulkUpdateReport, ProductBrandService
from xw_studio.services.products.catalog import Product
from xw_studio.services.products.field_bulk_service import (
    FieldBulkUpdateReport,
    ProductFieldBulkService,
)
from xw_studio.services.products.print_decision import PieceBlock, PrintDecisionEngine
from xw_studio.services.sevdesk.part_client import PartClient, SevdeskPart
from xw_studio.services.wix.client import WixProduct, WixProductsClient
from xw_studio.ui.modules.products.bulk_field_dialog import BulkFieldEditorDialog
from xw_studio.ui.modules.rechnungen.product_preflight_dialog import ProductPreflightDialog
from xw_studio.ui.modules.rechnungen.print_dialog import (
    _configure_missing_piece_print,
    prepare_piece_pdf_print,
    run_piece_pdf_print,
)
from xw_studio.ui.widgets.data_table import DataTable
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
    "Druck",
]

_ICONS_DIR = Path(__file__).resolve().parents[5] / "icons"


class _SyncPresenceDelegate(QStyledItemDelegate):
    """Paint compact per-system presence icons for the sync table."""

    _ICON_FILES = {
        "local": "cloud.png",
        "wix": "wix.png",
        "sevdesk": "sevdesk.png",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cache: dict[str, QPixmap] = {}
        self._tinted_cache: dict[str, QPixmap] = {}

    def _icon_for_key(self, key: str) -> QPixmap | None:
        if key in self._cache:
            pix = self._cache[key]
            return pix if not pix.isNull() else None
        file_name = self._ICON_FILES.get(key)
        if not file_name:
            self._cache[key] = QPixmap()
            return None
        pix = QPixmap(str(_ICONS_DIR / file_name))
        self._cache[key] = pix
        return pix if not pix.isNull() else None

    def _tinted_icon(self, key: str, color: QColor, size: int) -> QPixmap | None:
        cache_key = f"{key}:{color.name()}:{size}"
        if cache_key in self._tinted_cache:
            pix = self._tinted_cache[cache_key]
            return pix if not pix.isNull() else None
        source = self._icon_for_key(key)
        if source is None:
            self._tinted_cache[cache_key] = QPixmap()
            return None
        scaled = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        image = QImage(scaled.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.drawPixmap(0, 0, scaled)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(image.rect(), color)
        painter.end()
        tinted = QPixmap.fromImage(image)
        self._tinted_cache[cache_key] = tinted
        return tinted if not tinted.isNull() else None

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict):
            super().paint(painter, option, index)
            return
        icons = row_data.get("__icons__Status")
        if not isinstance(icons, list) or not icons:
            super().paint(painter, option, index)
            return

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, option.palette.alternateBase())

        painter.save()
        size = min(18, max(14, option.rect.height() - 6))
        gap = 6
        total_width = len(icons) * size + max(0, len(icons) - 1) * gap
        x = option.rect.x() + max(4, (option.rect.width() - total_width) // 2)
        y = option.rect.y() + max(2, (option.rect.height() - size) // 2)
        for key, present in icons:
            color = QColor("#16a34a") if present else QColor("#dc2626")
            target = option.rect.adjusted(0, 0, 0, 0)
            target.setX(x)
            target.setY(y)
            target.setWidth(size)
            target.setHeight(size)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(target)
            painter.restore()
            pix = self._tinted_icon(str(key), QColor("white"), max(8, size - 7))
            if pix is not None:
                painter.drawPixmap(x + (size - pix.width()) // 2, y + (size - pix.height()) // 2, pix)
            x += size + gap
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class _SyncConflictDelegate(QStyledItemDelegate):
    """Paint conflict icons without embedding QWidget instances per row."""

    _ICON_FILES = {
        "price": "priceNotSynced.png",
        "stock": "cloud.png",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cache: dict[str, QPixmap] = {}
        self._tinted_cache: dict[str, QPixmap] = {}

    def _icon_for_key(self, key: str) -> QPixmap | None:
        if key in self._cache:
            pix = self._cache[key]
            return pix if not pix.isNull() else None
        file_name = self._ICON_FILES.get(key)
        if not file_name:
            self._cache[key] = QPixmap()
            return None
        pix = QPixmap(str(_ICONS_DIR / file_name))
        self._cache[key] = pix
        return pix if not pix.isNull() else None

    def _tinted_icon(self, key: str, size: int) -> QPixmap | None:
        cache_key = f"{key}:{size}"
        if cache_key in self._tinted_cache:
            pix = self._tinted_cache[cache_key]
            return pix if not pix.isNull() else None
        source = self._icon_for_key(key)
        if source is None:
            self._tinted_cache[cache_key] = QPixmap()
            return None
        scaled = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        image = QImage(scaled.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.drawPixmap(0, 0, scaled)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(image.rect(), QColor("white"))
        painter.end()
        tinted = QPixmap.fromImage(image)
        self._tinted_cache[cache_key] = tinted
        return tinted if not tinted.isNull() else None

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict):
            super().paint(painter, option, index)
            return
        icons = row_data.get("__icons__Konflikt")
        if not isinstance(icons, list) or not icons:
            super().paint(painter, option, index)
            return

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, option.palette.alternateBase())

        painter.save()
        size = min(18, max(14, option.rect.height() - 6))
        gap = 6
        total_width = len(icons) * size + max(0, len(icons) - 1) * gap
        x = option.rect.x() + max(4, (option.rect.width() - total_width) // 2)
        y = option.rect.y() + max(2, (option.rect.height() - size) // 2)
        for key in icons:
            target = option.rect.adjusted(0, 0, 0, 0)
            target.setX(x)
            target.setY(y)
            target.setWidth(size)
            target.setHeight(size)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f59e0b"))
            painter.drawEllipse(target)
            painter.restore()
            pix = self._tinted_icon(str(key), max(8, size - 7))
            if pix is not None:
                painter.drawPixmap(x + (size - pix.width()) // 2, y + (size - pix.height()) // 2, pix)
            x += size + gap
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class _SyncActionDelegate(QStyledItemDelegate):
    """Render a compact per-product action in the sync table."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icons = {
            "create_sevdesk": QIcon(str(_ICONS_DIR / "createInSevdesk.png")),
            "print_config": QIcon(str(_ICONS_DIR / "printondemand.png")),
        }

    @staticmethod
    def _button_geometry(width: int, height: int) -> tuple[int, int, int, int]:
        button_width = min(28, max(22, width - 10))
        button_height = min(24, max(18, height - 6))
        x = max(4, (width - button_width) // 2)
        y = max(2, (height - button_height) // 2)
        return x, y, button_width, button_height

    @classmethod
    def hit_action(cls, *, local_x: float, local_y: float, width: int, height: int) -> bool:
        x, y, button_width, button_height = cls._button_geometry(width, height)
        return x <= int(local_x) <= x + button_width and y <= int(local_y) <= y + button_height

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        field = str(index.model().headerData(index.column(), Qt.Orientation.Horizontal) or "")
        enabled = isinstance(row_data, dict) and bool(row_data.get(f"__action_enabled__{field}"))
        if not enabled:
            super().paint(painter, option, index)
            return

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, option.palette.alternateBase())

        painter.save()
        x, y, button_width, button_height = self._button_geometry(option.rect.width(), option.rect.height())
        button_rect = option.rect.adjusted(0, 0, 0, 0)
        button_rect.setX(option.rect.x() + x)
        button_rect.setY(option.rect.y() + y)
        button_rect.setWidth(button_width)
        button_rect.setHeight(button_height)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor("#cbd5e1"))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(button_rect, 6, 6)
        icon_rect = button_rect.adjusted(5, 3, -5, -3)
        action_kind = str(row_data.get(f"__action_kind__{field}") or "create_sevdesk") if isinstance(row_data, dict) else ""
        icon = self._icons.get(action_kind) or self._icons["create_sevdesk"]
        icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 24:
            base.setHeight(24)
        return base


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
        self._brand_worker: BackgroundWorker | None = None
        self._product_create_worker: BackgroundWorker | None = None
        self._product_print_worker: BackgroundWorker | None = None
        self._sync_filter_text: str = ""
        self._sync_filter_status: str = ""
        self._sync_status_delegate = _SyncPresenceDelegate(self)
        self._sync_conflict_delegate = _SyncConflictDelegate(self)
        self._sync_action_delegate = _SyncActionDelegate(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        root.addWidget(self._build_sync_tab())

        self._load_sync_sources(refresh_sevdesk_cache=True)

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

        self._inv_table = DataTable(_INV_HEADERS)
        self._inv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._inv_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._inv_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
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
        self._inv_table.set_data(
            [
                {
                    "SKU": prod.sku,
                    "Name": prod.name,
                    "Kategorie": prod.category,
                    "Brand": prod.brand_name,
                    "Bestand": str(prod.on_hand),
                    "Preis EUR": prod.price_eur,
                    "Wix-ID": prod.wix_id,
                    "sevDesk-ID": prod.sevdesk_id,
                    "__align__Bestand": "center",
                    "__align__Preis EUR": "right",
                }
                for prod in rows
            ]
        )

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

        self._wix_table = DataTable(_WIX_HEADERS)
        self._wix_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._wix_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
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
        inv_skus = {p.sku for p in self._all_rows if p.sku}
        payload: list[dict[str, object]] = []
        for prod in rows:
            matched = prod.sku in inv_skus if prod.sku else False
            payload.append(
                {
                    "SKU": prod.sku,
                    "Name": prod.name,
                    "Brand": prod.brand_name,
                    "Preis": prod.price,
                    "Sichtbar": "ja" if prod.visible else "nein",
                    "Bestand": str(prod.inventory_quantity),
                    "Wix-ID": prod.id,
                    "Status": "verknuepft" if matched else "nur Wix",
                    "__align__Preis": "right",
                    "__align__Sichtbar": "center",
                    "__align__Bestand": "center",
                    "__fg__Status": "green" if matched else "yellow",
                }
            )
        self._wix_table.set_data(payload)

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
        self._sync_refresh_sevdesk_btn = QPushButton("sevDesk aktualisieren")
        self._sync_refresh_sevdesk_btn.clicked.connect(
            lambda: self._load_sync_sources(refresh_sevdesk_cache=True)
        )
        bar.addWidget(self._sync_refresh_sevdesk_btn)
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
        self._sync_print_btn = QPushButton("Auswahl drucken")
        self._sync_print_btn.clicked.connect(self._print_selected_product)
        self._sync_print_btn.setEnabled(False)
        bar.addWidget(self._sync_print_btn)
        self._sync_produce_btn = QPushButton("Drucken + Bestand")
        self._sync_produce_btn.setToolTip(
            "Druckt die Auswahl und erhoeht den Bestand erst nach bestaetigtem Druck."
        )
        self._sync_produce_btn.clicked.connect(self._produce_selected_product)
        self._sync_produce_btn.setEnabled(False)
        bar.addWidget(self._sync_produce_btn)
        self._sync_apply_btn = QPushButton("Wix -> Lokal uebernehmen")
        self._sync_apply_btn.clicked.connect(self._apply_wix_to_local)
        self._sync_apply_btn.setEnabled(False)
        bar.addWidget(self._sync_apply_btn)
        lay.addLayout(bar)

        self._sync_sevdesk_cache_lbl = QLabel("sevDesk-Cache: noch nicht aktualisiert")
        self._sync_sevdesk_cache_lbl.setObjectName("infoLabel")
        lay.addWidget(self._sync_sevdesk_cache_lbl)

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

        self._sync_table = DataTable(_SYNC_HEADERS)
        self._sync_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._sync_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._sync_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._sync_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._sync_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._sync_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self._sync_table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)
        self._sync_table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeMode.Fixed)
        self._sync_table.setColumnWidth(2, 86)
        self._sync_table.setColumnWidth(3, 72)
        self._sync_table.setColumnWidth(5, 92)
        self._sync_table.setColumnWidth(6, 76)
        self._sync_table.setColumnWidth(9, 44)
        self._sync_table.setColumnWidth(10, 44)
        self._sync_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self._sync_table.setItemDelegateForColumn(2, self._sync_status_delegate)
        self._sync_table.setItemDelegateForColumn(3, self._sync_conflict_delegate)
        self._sync_table.setItemDelegateForColumn(9, self._sync_action_delegate)
        self._sync_table.setItemDelegateForColumn(10, self._sync_action_delegate)
        self._sync_table.viewport().installEventFilter(self)
        lay.addWidget(self._sync_table, stretch=1)

        tip = QLabel(
            "Eine Liste fuer Lokal-DB, Wix und sevDesk. Der Status zeigt, ob ein Produkt sauber verknuepft ist, "
            "nur in einem System vorkommt oder Datenkonflikte hat."
        )
        tip.setWordWrap(True)
        tip.setObjectName("infoLabel")
        lay.addWidget(tip)

        plans_group = QGroupBox("Druckplaene (JSON, veraltet)")
        plans_lay = QVBoxLayout(plans_group)
        self._plans_editor = QPlainTextEdit()
        self._plans_editor.setPlaceholderText(
            '[{"sku": "XW-4-001", "min_qty": 1, "target_qty": 3, "pdf": "plans/xw-4-001.pdf"}]'
        )
        self._plans_editor.setMinimumHeight(130)
        plans_lay.addWidget(self._plans_editor)
        plans_btns = QHBoxLayout()
        self._plans_load_btn = QPushButton("Druckplaene laden")
        self._plans_load_btn.clicked.connect(self._load_print_plans)
        plans_btns.addWidget(self._plans_load_btn)
        self._plans_save_btn = QPushButton("Druckplaene speichern")
        self._plans_save_btn.clicked.connect(self._save_print_plans)
        plans_btns.addWidget(self._plans_save_btn)
        plans_btns.addStretch()
        plans_lay.addLayout(plans_btns)
        plans_group.setVisible(False)
        lay.addWidget(plans_group)
        return page

    def _load_sync_sources(self, _checked: bool = False, *, refresh_sevdesk_cache: bool = False) -> None:
        self._sync_load_btn.setEnabled(False)
        self._sync_refresh_sevdesk_btn.setEnabled(False)
        self._sync_apply_btn.setEnabled(False)
        if refresh_sevdesk_cache:
            self._sync_status_lbl.setText("Lade lokale Produkte, Wix und aktualisiere sevDesk-Cache...")
        else:
            self._sync_status_lbl.setText("Lade lokale Produkte, Wix und sevDesk...")

        def job() -> tuple[list[ProductRow], list[WixProduct], list[SevdeskPart], datetime | None]:
            inv: InventoryService = self._container.resolve(InventoryService)
            wix_client: WixProductsClient = self._container.resolve(WixProductsClient)
            part_client: PartClient = self._container.resolve(PartClient)

            local = inv.list_products()
            wix = wix_client.list_products()
            sevdesk: list[SevdeskPart] = []
            try:
                sevdesk = part_client.list_parts(refresh_cache=refresh_sevdesk_cache)
            except Exception as exc:  # noqa: BLE001
                logger.warning("sevDesk products not available for sync: %s", exc)
            return (local, wix, sevdesk, part_client.parts_cache_updated_at)

        self._sevdesk_worker = BackgroundWorker(job)
        self._sevdesk_worker.signals.result.connect(self._on_sync_sources_loaded)
        self._sevdesk_worker.signals.error.connect(self._on_sync_sources_error)
        self._sevdesk_worker.start()

    def _on_sync_sources_loaded(self, payload: object) -> None:
        self._sync_load_btn.setEnabled(True)
        self._sync_refresh_sevdesk_btn.setEnabled(True)
        if not isinstance(payload, tuple) or len(payload) != 4:
            return
        local_rows, wix_rows, sevdesk_rows, cache_updated_at = payload
        if not isinstance(local_rows, list) or not isinstance(wix_rows, list) or not isinstance(sevdesk_rows, list):
            return
        self._all_rows = [r for r in local_rows if isinstance(r, ProductRow)]
        self._wix_rows = [r for r in wix_rows if isinstance(r, WixProduct)]
        self._sevdesk_rows = [r for r in sevdesk_rows if isinstance(r, SevdeskPart)]

        self._sync_rows = self._build_sync_rows()
        self._sync_fields_btn.setEnabled(bool(self._sync_rows))
        self._sync_brand_btn.setEnabled(bool(self._sync_rows))
        self._sync_print_btn.setEnabled(bool(self._sync_rows))
        self._sync_produce_btn.setEnabled(bool(self._sync_rows))
        self._sync_search.refresh_suggestions()
        self._apply_sync_filters()
        conflicts = sum(1 for row in self._sync_rows if row.status != "sauber verknuepft")
        self._sync_status_lbl.setText(
            f"Sync-Vergleich geladen: {len(self._sync_rows)} SKU, Konflikte: {conflicts}"
        )
        self._sync_sevdesk_cache_lbl.setText(
            f"sevDesk-Cache: {self._format_cache_timestamp(cache_updated_at)}"
        )
        self._sync_apply_btn.setEnabled(bool(self._wix_rows))

    def _on_sync_sources_error(self, exc: BaseException) -> None:
        self._sync_load_btn.setEnabled(True)
        self._sync_refresh_sevdesk_btn.setEnabled(True)
        self._sync_fields_btn.setEnabled(False)
        self._sync_brand_btn.setEnabled(False)
        self._sync_print_btn.setEnabled(False)
        self._sync_produce_btn.setEnabled(False)
        self._sync_apply_btn.setEnabled(False)
        self._sync_status_lbl.setText(f"Fehler: {exc}")
        logger.exception("Sync source load failed: %s", exc)

    @staticmethod
    def _format_cache_timestamp(value: object) -> str:
        if isinstance(value, datetime):
            return value.astimezone().strftime("%d.%m.%Y %H:%M:%S")
        return "noch nicht aktualisiert"

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
        payload: list[dict[str, object]] = []
        for row in rows:
            stock_value = row.local_stock if row.local_present else (row.wix_stock if row.wix_stock is not None else row.sevdesk_stock)
            conflict_specs = self._conflict_icon_specs(row)
            payload.append(
                {
                    "SKU": row.sku,
                    "Name": row.name,
                    "Status": self._sync_presence_sort_key(row),
                    "Konflikt": "|".join(key for key, _tooltip in conflict_specs),
                    "Brand": row.local_brand or row.wix_brand,
                    "Preis": self._format_eur(row.local_price or row.wix_price or row.sevdesk_price),
                    "Bestand": "" if stock_value is None else str(stock_value),
                    "Wix-ID": row.wix_id,
                    "sevDesk-ID": row.sevdesk_id,
                    "Aktion": row.sku if row.can_create_sevdesk else "",
                    "Druck": row.sku if row.local_present else "",
                    "__align__Preis": "right",
                    "__align__Bestand": "center",
                    "__tooltip__Status": self._sync_presence_tooltip(row),
                    "__tooltip__Konflikt": self._sync_conflict_tooltip(conflict_specs),
                    "__tooltip__Aktion": "In sevDesk anlegen" if row.can_create_sevdesk else "",
                    "__tooltip__Druck": (
                        "PDF-Pfad und Druckplan direkt fuer dieses Produkt pflegen"
                        if row.local_present
                        else ""
                    ),
                    "__icons__Status": [
                        ("local", row.local_present),
                        ("wix", row.wix_present),
                        ("sevdesk", row.sevdesk_present),
                    ],
                    "__icons__Konflikt": [key for key, _tooltip in conflict_specs],
                    "__action_enabled__Aktion": row.can_create_sevdesk,
                    "__action_kind__Aktion": "create_sevdesk",
                    "__action_enabled__Druck": row.local_present,
                    "__action_kind__Druck": "print_config",
                }
            )
        self._sync_table.set_data(payload)

    def _conflict_icon_specs(self, row: _SyncRow) -> list[tuple[str, str]]:
        labels: list[tuple[str, str]] = []
        if row.local_present and row.wix_present and (row.local_price or "") != (row.wix_price or ""):
            labels.append(("price", "Preis nicht mit Wix synchron"))
        if row.local_present and row.sevdesk_present and (row.local_price or "") != (row.sevdesk_price or ""):
            labels.append(("price", "Preis nicht mit sevDesk synchron"))
        if row.local_present and row.wix_present and row.wix_stock != row.local_stock:
            labels.append(("stock", "Bestand nicht mit Wix synchron"))
        if row.local_present and row.sevdesk_present and row.sevdesk_stock != row.local_stock:
            labels.append(("stock", "Bestand nicht mit sevDesk synchron"))
        return labels

    @staticmethod
    def _sync_presence_sort_key(row: _SyncRow) -> str:
        return "".join("1" if present else "0" for present in (row.local_present, row.wix_present, row.sevdesk_present))

    @staticmethod
    def _sync_presence_tooltip(row: _SyncRow) -> str:
        return "\n".join(
            [
                f"Lokal DB: {'vorhanden' if row.local_present else 'fehlt'}",
                f"Wix: {'vorhanden' if row.wix_present else 'fehlt'}",
                f"sevDesk: {'vorhanden' if row.sevdesk_present else 'fehlt'}",
            ]
        )

    @staticmethod
    def _sync_conflict_tooltip(conflicts: list[tuple[str, str]]) -> str:
        if not conflicts:
            return "Keine Konflikte"
        return "\n".join(text for _key, text in conflicts)

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
        return self._selected_skus_from_data_table(self._sync_table)

    def _print_selected_product(self) -> None:
        skus = self._selected_product_skus()
        if not skus:
            QMessageBox.information(self, "Produktdruck", "Bitte zuerst ein Produkt auswaehlen.")
            return
        sku = skus[0]
        row = self._local_product_by_sku(sku)
        if row is None:
            QMessageBox.information(
                self,
                "Produktdruck",
                "Fuer diese SKU gibt es noch keinen lokalen Produktdatensatz mit Druckkonfiguration.",
            )
            return
        copies, ok = QInputDialog.getInt(self, "Produktdruck", "Anzahl:", 1, 1, 999, 1)
        if not ok:
            return
        piece = self._piece_from_product_row(row)
        if run_piece_pdf_print(self, self._container, piece=piece, copies=copies):
            self._sync_status_lbl.setText(f"Produktdruck gestartet: {row.sku} ({copies}x)")

    def _produce_selected_product(self) -> None:
        if self._product_print_worker is not None and self._product_print_worker.isRunning():
            return
        skus = self._selected_product_skus()
        if not skus:
            QMessageBox.information(self, "Produktion", "Bitte zuerst ein Produkt auswaehlen.")
            return
        row = self._local_product_by_sku(skus[0])
        if row is None:
            QMessageBox.information(
                self,
                "Produktion",
                "Fuer diese SKU gibt es keinen lokalen Produktdatensatz.",
            )
            return
        if not str(row.sevdesk_id or "").strip():
            QMessageBox.warning(
                self,
                "Produktion",
                "Drucken + Bestand benoetigt eine sevDesk-Verknuepfung.",
            )
            return
        copies, ok = QInputDialog.getInt(self, "Produktion", "Anzahl:", 1, 1, 999, 1)
        if not ok:
            return
        piece = self._piece_from_product_row(row)
        print_job = prepare_piece_pdf_print(
            self,
            self._container,
            piece=piece,
            copies=copies,
            wait=True,
        )
        if print_job is None:
            return

        self._set_product_print_buttons_enabled(False)
        self._sync_status_lbl.setText(f"Produktion laeuft: {row.sku} ({copies}x)")

        def worker_job() -> dict[str, object]:
            print_job()
            try:
                engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
                new_stock = engine.record_print_and_update_sevdesk(
                    piece,
                    copies,
                    invoice_ref="Produkte-Menue",
                )
                if new_stock <= 0:
                    raise RuntimeError("sevDesk-Bestand konnte nicht aktualisiert werden")
                inventory: InventoryService = self._container.resolve(InventoryService)
            except Exception as exc:  # noqa: BLE001 - stock systems have varied failures
                logger.warning("Stock update after production print failed for %s: %s", row.sku, exc)
                return {
                    "sku": row.sku,
                    "quantity": copies,
                    "new_stock": None,
                    "stock_warning": str(exc),
                    "local_warning": "",
                }
            local_warning = ""
            try:
                inventory.set_product_stock(row.sku, new_stock)
            except Exception as exc:  # noqa: BLE001 - sevDesk is already authoritative here
                local_warning = str(exc)
                logger.warning("Local stock cache update failed for %s: %s", row.sku, exc)
            return {
                "sku": row.sku,
                "quantity": copies,
                "new_stock": new_stock,
                "stock_warning": "",
                "local_warning": local_warning,
            }

        self._product_print_worker = BackgroundWorker(worker_job)
        self._product_print_worker.signals.result.connect(self._on_product_production_result)
        self._product_print_worker.signals.error.connect(self._on_product_production_error)
        self._product_print_worker.signals.finished.connect(self._on_product_production_finished)
        self._product_print_worker.start()

    def _on_product_production_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        sku = str(data.get("sku") or "Produkt")
        quantity = int(data.get("quantity") or 0)
        warning = str(data.get("stock_warning") or "").strip()
        if warning:
            self._sync_status_lbl.setText(
                f"Druck erfolgreich, Bestand nicht gebucht: {sku} ({quantity}x)"
            )
            QMessageBox.warning(
                self,
                "Produktion teilweise erfolgreich",
                f"{sku} wurde {quantity}x gedruckt, der Bestand aber nicht gebucht:\n\n{warning}",
            )
            return
        new_stock = int(data.get("new_stock") or 0)
        local_warning = str(data.get("local_warning") or "").strip()
        self._sync_status_lbl.setText(
            f"Druck erfolgreich, Bestand gebucht: {sku} ({quantity}x, neu {new_stock})"
        )
        if local_warning:
            QMessageBox.warning(
                self,
                "Bestand gebucht",
                "Der sevDesk-Bestand wurde gebucht, der lokale Cache konnte aber nicht "
                f"aktualisiert werden:\n\n{local_warning}",
            )
        self._load_sync_sources(refresh_sevdesk_cache=True)

    def _on_product_production_error(self, exc: BaseException) -> None:
        self._sync_status_lbl.setText("Druck fehlgeschlagen, Bestand nicht gebucht.")
        QMessageBox.critical(
            self,
            "Produktion fehlgeschlagen",
            f"Der Druck ist fehlgeschlagen. Der Bestand wurde nicht veraendert:\n\n{exc}",
        )

    def _on_product_production_finished(self) -> None:
        self._product_print_worker = None
        self._set_product_print_buttons_enabled(bool(self._sync_rows))

    def _set_product_print_buttons_enabled(self, enabled: bool) -> None:
        self._sync_print_btn.setEnabled(enabled)
        self._sync_produce_btn.setEnabled(enabled)

    def _local_product_by_sku(self, sku: str) -> ProductRow | None:
        wanted = str(sku or "").strip().upper()
        for row in self._all_rows:
            if row.sku.strip().upper() == wanted:
                return row
        return None

    def _manage_product_print_config(self, sku: str) -> None:
        row = self._local_product_by_sku(sku)
        if row is None:
            QMessageBox.information(
                self,
                "Druckplan",
                "Fuer diese SKU gibt es noch keinen lokalen Produktdatensatz.",
            )
            return
        piece = self._piece_from_product_row(row)
        if not _configure_missing_piece_print(self, self._container, piece):
            self._sync_status_lbl.setText(f"Druckkonfiguration fuer {row.sku} nicht geaendert.")
            return
        inv: InventoryService = self._container.resolve(InventoryService)
        self._all_rows = inv.list_products()
        self._sync_rows = self._build_sync_rows()
        self._apply_sync_filters()
        self._sync_status_lbl.setText(f"Druckkonfiguration fuer {row.sku} gespeichert.")

    @staticmethod
    def _piece_from_product_row(row: ProductRow) -> PieceBlock:
        product = Product(
            id=f"settings::{row.sku}",
            sku=row.sku,
            name=row.name,
            category=row.category,
            brand_name=row.brand_name,
            brand_id=row.brand_id,
            sevdesk_part_id=row.sevdesk_id,
            wix_product_id=row.wix_id,
            print_file_path=row.print_file_path,
        )
        return PieceBlock(
            sku=row.sku,
            name=row.name,
            qty_needed=1,
            print_profile_id=str(row.print_profile_id or "").strip(),
            print_plan=[entry for entry in (row.print_plan or []) if isinstance(entry, dict)],
            product=product,
        )

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
        if self._save_worker is not None and self._save_worker.isRunning():
            return
        inv: InventoryService = self._container.resolve(InventoryService)
        self._plans_load_btn.setEnabled(False)
        self._plans_load_btn.setText("Lade...")
        self._save_worker = BackgroundWorker(inv.load_print_plans)
        self._save_worker.signals.result.connect(self._on_print_plans_loaded)
        self._save_worker.signals.error.connect(self._on_print_plans_error)
        self._save_worker.signals.finished.connect(self._on_print_plans_finished)
        self._save_worker.start()

    def _on_print_plans_loaded(self, payload: object) -> None:
        plans = payload if isinstance(payload, list) else []
        self._plans_editor.setPlainText(json.dumps(plans, ensure_ascii=False, indent=2))
        self._sync_status_lbl.setText(f"{len(plans)} Druckplaene geladen")

    def _save_print_plans(self) -> None:
        if self._save_worker is not None and self._save_worker.isRunning():
            return
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
        self._plans_save_btn.setEnabled(False)
        self._plans_save_btn.setText("Speichere...")

        def job() -> int:
            inv.save_print_plans(data)
            return len(data)

        self._save_worker = BackgroundWorker(job)
        self._save_worker.signals.result.connect(self._on_print_plans_saved)
        self._save_worker.signals.error.connect(self._on_print_plans_error)
        self._save_worker.signals.finished.connect(self._on_print_plans_finished)
        self._save_worker.start()

    def _on_print_plans_saved(self, payload: object) -> None:
        count = int(payload) if isinstance(payload, int) else 0
        self._sync_status_lbl.setText(f"{count} Druckplaene gespeichert")
        QMessageBox.information(self, "Druckplaene", f"{count} Druckplan-Eintraege gespeichert.")

    def _on_print_plans_error(self, exc: Exception) -> None:
        self._sync_status_lbl.setText(f"Druckplan-Fehler: {exc}")
        QMessageBox.warning(self, "Druckplaene", str(exc))

    def _on_print_plans_finished(self) -> None:
        self._save_worker = None
        self._plans_load_btn.setEnabled(True)
        self._plans_load_btn.setText("Druckplaene laden")
        self._plans_save_btn.setEnabled(True)
        self._plans_save_btn.setText("Druckplaene speichern")

    def _selected_inventory_skus(self) -> list[str]:
        if hasattr(self, "_inv_table"):
            return self._selected_skus_from_data_table(self._inv_table)
        return self._selected_product_skus()

    def _selected_wix_skus(self) -> list[str]:
        if hasattr(self, "_wix_table"):
            return self._selected_skus_from_data_table(self._wix_table)
        return self._selected_product_skus()

    @staticmethod
    def _selected_skus_from_data_table(table: DataTable) -> list[str]:
        skus: list[str] = []
        for row in table.selected_rows_data():
            sku = str(row.get("SKU") or "").strip()
            if sku:
                skus.append(sku)
        return skus

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

        wix_products = list(self._wix_rows)
        self._sync_fields_btn.setEnabled(False)
        self._sync_status_lbl.setText("Produktfelder werden aktualisiert...")

        def job() -> FieldBulkUpdateReport:
            return service.apply_field_update(
                skus=skus,
                field_name=field_name,
                operator=operator,
                value=value,
                sync_wix=sync_wix,
                wix_products=wix_products,
            )

        self._save_worker = BackgroundWorker(job)
        self._save_worker.signals.result.connect(
            lambda payload: self._on_field_update_done(service, field_name, sync_wix, payload)
        )
        self._save_worker.signals.error.connect(self._on_field_update_error)
        self._save_worker.signals.finished.connect(lambda: setattr(self, "_save_worker", None))
        self._save_worker.start()

    def _on_field_update_done(
        self,
        service: ProductFieldBulkService,
        field_name: str,
        sync_wix: bool,
        payload: object,
    ) -> None:
        self._sync_fields_btn.setEnabled(True)
        if not isinstance(payload, FieldBulkUpdateReport):
            self._sync_status_lbl.setText("Produktfeld-Aktualisierung lieferte kein Ergebnis")
            return
        fields = service.get_editable_fields()
        field_definition = fields.get(field_name)
        field_label = field_definition.label if field_definition is not None else field_name
        message = (
            f"Feld: {field_label}\n"
            f"Operation: {payload.operator}\n"
            f"Wert: {payload.value}\n\n"
            f"Geaendert (lokal): {payload.changed}\n"
            f"Uebersprungen: {payload.skipped}\n"
            f"Fehler: {payload.failed}\n"
        )
        if sync_wix:
            message += (
                f"\nWix versucht: {payload.wix_attempted}\n"
                f"Wix erfolgreich: {payload.wix_updated}\n"
                f"Wix Fehler: {payload.wix_failed}"
            )
        self._sync_status_lbl.setText(f"Produktfelder aktualisiert: {payload.changed} geaendert")
        QMessageBox.information(self, "Felder aendern - Abgeschlossen", message)
        self._load_sync_sources()

    def _on_field_update_error(self, exc: Exception) -> None:
        self._sync_fields_btn.setEnabled(True)
        self._sync_status_lbl.setText(f"Feld-Aktualisierung fehlgeschlagen: {exc}")
        QMessageBox.warning(self, "Felder aendern - Fehler", f"Fehler: {exc}")

    def _bulk_edit_wix_fields(self) -> None:
        self._run_bulk_field_dialog(self._selected_wix_skus(), source_label="Wix")

    def _create_selected_wix_product_in_sevdesk(self, sku: str) -> None:
        if self._product_create_worker is not None and self._product_create_worker.isRunning():
            return
        normalized_sku = str(sku or "").strip().upper()
        if not normalized_sku:
            return
        wix_product = next((row for row in self._wix_rows if row.sku.strip().upper() == normalized_sku), None)
        if wix_product is None:
            QMessageBox.warning(self, "sevDesk", f"Wix-Produkt fuer SKU {normalized_sku} nicht gefunden.")
            return

        service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
        self._sync_status_lbl.setText(f"sevDesk-Produktdialog fuer {normalized_sku} wird vorbereitet...")

        def job() -> ProductPreflightPlan:
            return service.build_manual_wix_product_plan(
                sku=wix_product.sku,
                wix_name=wix_product.name,
                wix_product_id=wix_product.id,
                wix_description="",
                wix_price_gross=float(wix_product.price) if str(wix_product.price or "").strip() else None,
                is_digital=False,
            )

        self._product_create_worker = BackgroundWorker(job)
        worker = self._product_create_worker
        worker.signals.result.connect(
            lambda payload: self._on_sevdesk_product_plan_ready(
                service, wix_product, payload
            )
        )
        worker.signals.error.connect(self._on_sevdesk_product_error)
        worker.signals.finished.connect(
            lambda current=worker: self._clear_product_create_worker(current)
        )
        worker.start()

    def _clear_product_create_worker(self, worker: BackgroundWorker) -> None:
        if self._product_create_worker is worker:
            self._product_create_worker = None

    def _on_sevdesk_product_plan_ready(
        self,
        service: DraftInvoiceService,
        wix_product: WixProduct,
        payload: object,
    ) -> None:
        if not isinstance(payload, ProductPreflightPlan):
            self._on_sevdesk_product_error(RuntimeError("Produktplan ist ungueltig"))
            return
        plan = payload

        issue = plan.issues[0] if plan.issues else None
        if issue is None:
            QMessageBox.warning(self, "sevDesk", "Produktdialog konnte nicht vorbereitet werden.")
            return

        dialog = ProductPreflightDialog(issue, part_categories=plan.part_categories, parent=self)
        decision = dialog.show_dialog()
        if decision is None:
            decision = ProductIssueDecision(action="skip", draft=issue.draft)
        if decision.action != "create_part":
            self._sync_status_lbl.setText("sevDesk-Produktanlage abgebrochen")
            return

        self._sync_status_lbl.setText(f"Produkt {wix_product.sku} wird in sevDesk angelegt...")

        def job() -> SevdeskPart:
            created = service.create_part_from_decision(issue, decision)
            self._upsert_local_product_from_wix(wix_product, sevdesk_id=created.id)
            return created

        self._product_create_worker = BackgroundWorker(job)
        worker = self._product_create_worker
        worker.signals.result.connect(self._on_sevdesk_product_created)
        worker.signals.error.connect(self._on_sevdesk_product_error)
        worker.signals.finished.connect(
            lambda current=worker: self._clear_product_create_worker(current)
        )
        worker.start()

    def _on_sevdesk_product_created(self, payload: object) -> None:
        if not isinstance(payload, SevdeskPart):
            return
        created = payload
        self._sync_status_lbl.setText(f"Produkt {created.sku} in sevDesk angelegt")
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
        if self._brand_worker is not None and self._brand_worker.isRunning():
            return
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
        self._sync_brand_btn.setEnabled(False)
        self._sync_status_lbl.setText("Brand-Vorschau wird berechnet...")

        def job() -> BrandBulkUpdateReport:
            return service.preview_local_brand_update(skus, target_brand)

        self._brand_worker = BackgroundWorker(job)
        worker = self._brand_worker
        worker.signals.result.connect(
            lambda payload: self._on_brand_preview_ready(service, skus, target_brand, payload)
        )
        worker.signals.error.connect(self._on_brand_update_error)
        worker.signals.finished.connect(
            lambda current=worker: self._clear_brand_worker_if_current(current)
        )
        worker.start()

    def _clear_brand_worker_if_current(self, worker: BackgroundWorker) -> None:
        if self._brand_worker is worker:
            self._brand_worker = None

    def _on_brand_preview_ready(
        self,
        service: ProductBrandService,
        skus: list[str],
        target_brand: str,
        payload: object,
    ) -> None:
        if not isinstance(payload, BrandBulkUpdateReport):
            self._sync_brand_btn.setEnabled(True)
            self._sync_status_lbl.setText("Brand-Vorschau lieferte kein Ergebnis")
            return
        preview = payload
        if preview.requested == 0:
            self._sync_brand_btn.setEnabled(True)
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
            self._sync_brand_btn.setEnabled(True)
            self._sync_status_lbl.setText("Brand-Update abgebrochen")
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

        self._sync_status_lbl.setText("Brand wird lokal und in Wix aktualisiert...")

        def job() -> BrandBulkUpdateReport:
            return service.apply_brand_update(
                skus,
                target_brand,
                sync_wix=sync_wix,
                create_missing_wix_brand=create_missing_wix_brand,
            )

        self._brand_worker = BackgroundWorker(job)
        worker = self._brand_worker
        worker.signals.result.connect(self._on_brand_update_done)
        worker.signals.error.connect(self._on_brand_update_error)
        worker.signals.finished.connect(
            lambda current=worker: self._clear_brand_worker_if_current(current)
        )
        worker.start()

    def _on_brand_update_done(self, payload: object) -> None:
        self._sync_brand_btn.setEnabled(True)
        if not isinstance(payload, BrandBulkUpdateReport):
            self._sync_status_lbl.setText("Brand-Update lieferte kein Ergebnis")
            return
        report = payload
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

    def _on_sevdesk_product_error(self, exc: Exception) -> None:
        self._sync_status_lbl.setText(f"sevDesk-Produktanlage fehlgeschlagen: {exc}")
        QMessageBox.warning(self, "sevDesk", f"Produkt konnte nicht angelegt werden:\n{exc}")

    def _on_brand_update_error(self, exc: Exception) -> None:
        self._sync_brand_btn.setEnabled(True)
        self._sync_status_lbl.setText(f"Brand-Update fehlgeschlagen: {exc}")
        QMessageBox.warning(self, "Brand-Update", str(exc))

    def _bulk_edit_fields(self) -> None:
        """Open dialog for bulk product field editing."""
        self._run_bulk_field_dialog(self._selected_product_skus(), source_label="Produkte")

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self._sync_table.viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                index = self._sync_table.indexAt(event.position().toPoint())
                if index.isValid() and index.column() in {9, 10}:
                    row_data = index.data(Qt.ItemDataRole.UserRole)
                    field = str(index.model().headerData(index.column(), Qt.Orientation.Horizontal) or "")
                    if isinstance(row_data, dict) and bool(row_data.get(f"__action_enabled__{field}")):
                        rect = self._sync_table.visualRect(index)
                        local_x = event.position().x() - rect.x()
                        local_y = event.position().y() - rect.y()
                        if self._sync_action_delegate.hit_action(
                            local_x=local_x,
                            local_y=local_y,
                            width=rect.width(),
                            height=rect.height(),
                        ):
                            sku = str(row_data.get("SKU") or "").strip()
                            if sku:
                                action_kind = str(row_data.get(f"__action_kind__{field}") or "").strip()
                                if action_kind == "print_config":
                                    self._manage_product_print_config(sku)
                                else:
                                    self._create_selected_wix_product_in_sevdesk(sku)
                                return True
        return super().eventFilter(watched, event)

