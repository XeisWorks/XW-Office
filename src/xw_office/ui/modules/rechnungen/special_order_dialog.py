"""Dialog for creating special-order Wix payment links."""
from __future__ import annotations

import re

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.container import Container
from xw_office.core.worker import BackgroundWorker
from xw_office.services.special_orders import SpecialOrderItem, SpecialOrderService

_HANDLING_NAME = "Digital Delivery Handling"


class SpecialOrderDialog(QDialog):
    """Create one-off physical/digital special-order payment links."""

    def __init__(self, container: Container, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._container = container
        self._service: SpecialOrderService = container.resolve(SpecialOrderService)
        self._products: list[object] = []
        self._selected_products: list[object] = []
        self._worker: BackgroundWorker | None = None
        self._build_ui()
        QTimer.singleShot(0, self._load_products)

    def _build_ui(self) -> None:
        self.setWindowTitle("Sonderauftrag")
        self.setMinimumSize(820, 780)
        root = QVBoxLayout(self)

        form = QFormLayout()
        self._mode = QComboBox()
        self._mode.addItem("Physische Sonderanfertigung", "physical_custom")
        self._mode.addItem("Digitale Sonderanfertigung", "digital_custom")
        self._mode.addItem("Bestehende Artikel digital liefern", "digital_sheet_music")
        self._mode.currentIndexChanged.connect(self._update_mode)
        form.addRow("Art:", self._mode)

        self._title = QLineEdit()
        form.addRow("Titel:", self._title)
        self._description = QTextEdit()
        self._description.setMinimumHeight(90)
        form.addRow("Beschreibung:", self._description)
        self._price = QDoubleSpinBox()
        self._price.setRange(0.01, 99999.0)
        self._price.setDecimals(2)
        self._price.setSuffix(" EUR")
        self._price.setValue(24.0)
        form.addRow("Preis:", self._price)
        self._qty = QSpinBox()
        self._qty.setRange(1, 999)
        self._qty.setValue(1)
        form.addRow("Menge:", self._qty)
        self._custom_fields = [
            self._title,
            self._description,
            self._price,
            self._qty,
        ]
        root.addLayout(form)

        self._product_label = QLabel("Wix-Artikel suchen:")
        root.addWidget(self._product_label)
        self._product_filter = QLineEdit()
        self._product_filter.setPlaceholderText("SKU oder Name suchen")
        self._product_filter.textChanged.connect(self._filter_products)
        root.addWidget(self._product_filter)
        self._product_list = QListWidget()
        self._product_list.setMinimumHeight(330)
        self._product_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._product_list.itemClicked.connect(self._add_selected_product)
        root.addWidget(self._product_list, stretch=3)

        self._selected_label = QLabel("Ausgewaehlte Artikel:")
        root.addWidget(self._selected_label)
        self._selected_list = QListWidget()
        self._selected_list.setMinimumHeight(240)
        self._selected_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        root.addWidget(self._selected_list, stretch=2)

        row = QHBoxLayout()
        self._status = QLabel("-")
        row.addWidget(self._status, stretch=1)
        self._create_btn = QPushButton("Payment Link erstellen + kopieren")
        self._create_btn.clicked.connect(self._create_link)
        row.addWidget(self._create_btn)
        root.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._update_mode()

    def _load_products(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._status.setText("Lade Wix-Produkte...")
        self._worker = BackgroundWorker(self._service.list_wix_products)
        self._worker.signals.result.connect(self._on_products_loaded)
        self._worker.signals.error.connect(lambda exc: self._status.setText(str(exc)))
        self._worker.signals.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.start()

    def _on_products_loaded(self, payload: object) -> None:
        self._products = list(payload) if isinstance(payload, list) else []
        self._filter_products()
        self._status.setText(f"Wix-Produkte: {len(self._products)}")

    def _filter_products(self) -> None:
        query = self._product_filter.text().strip().casefold() if hasattr(self, "_product_filter") else ""
        self._product_list.clear()
        for product in self._products:
            sku = str(getattr(product, "sku", "") or "")
            name = str(getattr(product, "name", "") or "")
            if name.strip().casefold() == _HANDLING_NAME.casefold():
                continue
            if self._is_selected_product(product):
                continue
            if query and query not in f"{sku} {name}".casefold():
                continue
            price = str(getattr(product, "price", "") or "")
            item = QListWidgetItem(f"{sku} | {name} | {price} EUR")
            item.setData(256, product)
            self._product_list.addItem(item)

    def _update_mode(self) -> None:
        is_existing_articles = self._mode.currentData() == "digital_sheet_music"
        self._product_label.setVisible(is_existing_articles)
        self._product_filter.setVisible(is_existing_articles)
        self._product_list.setVisible(is_existing_articles)
        self._selected_label.setVisible(is_existing_articles)
        self._selected_list.setVisible(is_existing_articles)
        for widget in self._custom_fields:
            widget.setVisible(not is_existing_articles)
        self.layout().invalidate()

    def _add_selected_product(self, item: QListWidgetItem) -> None:
        product = item.data(256)
        if product is None or self._is_selected_product(product):
            return
        self._selected_products.append(product)
        self._refresh_selected_products()
        self._product_filter.clear()
        self._filter_products()

    def _remove_product(self, product: object) -> None:
        product_id = str(getattr(product, "id", "") or "").strip()
        product_sku = str(getattr(product, "sku", "") or "").strip()
        self._selected_products = [
            selected
            for selected in self._selected_products
            if not self._same_product(selected, product_id=product_id, product_sku=product_sku)
        ]
        self._refresh_selected_products()
        self._filter_products()

    def _refresh_selected_products(self) -> None:
        self._selected_list.clear()
        for product in self._selected_products:
            sku = str(getattr(product, "sku", "") or "")
            name = str(getattr(product, "name", "") or "")
            price = str(getattr(product, "price", "") or "")
            item = QListWidgetItem(f"{sku} | {name} | {price} EUR")
            item.setData(256, product)
            self._selected_list.addItem(item)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(8)
            label = QLabel(f"{sku} | {name} | {price} EUR")
            label.setToolTip(f"{sku} | {name} | {price} EUR")
            row_layout.addWidget(label, stretch=1)
            remove_btn = QPushButton("✕")
            remove_btn.setToolTip("Artikel entfernen")
            remove_btn.setFixedWidth(30)
            remove_btn.clicked.connect(lambda _checked=False, product=product: self._remove_product(product))
            row_layout.addWidget(remove_btn)
            item.setSizeHint(row.sizeHint())
            self._selected_list.setItemWidget(item, row)
        self._sync_price_from_selection()

    def _sync_price_from_selection(self) -> None:
        total = 0.0
        for product in self._selected_products:
            price = self._product_price(product)
            if price > 0:
                total += price
        self._status.setText(f"Ausgewaehlt: {len(self._selected_products)} | Summe Artikel: {total:.2f} EUR")

    def _create_link(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        mode = str(self._mode.currentData())
        if mode != "digital_sheet_music" and not self._title.text().strip():
            QMessageBox.warning(self, "Sonderauftrag", "Titel ist Pflicht.")
            return
        try:
            items = self._build_items(mode)
        except RuntimeError as exc:
            QMessageBox.warning(self, "Sonderauftrag", str(exc))
            return
        title = self._payment_link_title() if mode == "digital_sheet_music" else self._title.text().strip()
        description = (
            self._payment_link_description()
            if mode == "digital_sheet_music"
            else self._description.toPlainText().strip()
        )

        def job() -> str:
            link = self._service.create_payment_link(
                mode=mode,  # type: ignore[arg-type]
                title=title,
                description=description,
                items=items,
                customer_email="",
                customer_first_name="",
                customer_last_name="",
            )
            return link.url

        self._create_btn.setEnabled(False)
        self._status.setText("Erstelle Payment Link...")
        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_link_created)
        self._worker.signals.error.connect(self._on_link_error)
        self._worker.signals.finished.connect(lambda: self._create_btn.setEnabled(True))
        self._worker.signals.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.start()

    def _build_items(self, mode: str) -> list[SpecialOrderItem]:
        if mode == "digital_sheet_music":
            items: list[SpecialOrderItem] = []
            selected_products = [
                product
                for product in self._selected_products
                if str(getattr(product, "name", "") or "").strip().casefold() != _HANDLING_NAME.casefold()
            ]
            if not selected_products:
                raise RuntimeError("Bitte mindestens ein Wix-Produkt auswaehlen.")
            handling = self._find_handling_product()
            if handling is None:
                raise RuntimeError("Wix-Produkt 'Digital Delivery Handling' wurde nicht gefunden.")
            handling_price = self._product_price(handling)
            if handling_price <= 0:
                raise RuntimeError("Wix-Bruttopreis fuer 'Digital Delivery Handling' fehlt oder ist 0.")
            for product in selected_products:
                price = self._product_price(product)
                product_title = str(getattr(product, "name", "") or "").strip()
                if price <= 0:
                    name = product_title or "ausgewaehltes Produkt"
                    raise RuntimeError(f"Wix-Bruttopreis fuer '{name}' fehlt oder ist 0.")
                description = (
                    "Licensed digital sheet music delivery. "
                    "Physical shipment and stock handling are intentionally bypassed."
                )
                items.append(
                    SpecialOrderItem(
                        type="CATALOG",
                        catalog_item_id=str(getattr(product, "id", "") or ""),
                        sku=str(getattr(product, "sku", "") or ""),
                        name=product_title,
                        description=description,
                        price=f"{price:.2f}",
                    )
                )
                items.append(
                    SpecialOrderItem(
                        type="CATALOG",
                        catalog_item_id=str(getattr(handling, "id", "") or ""),
                        sku=str(getattr(handling, "sku", "") or ""),
                        name=str(getattr(handling, "name", "") or _HANDLING_NAME),
                        description=f"Digital delivery handling for: {product_title}",
                        price=f"{handling_price:.2f}",
                    )
                )
            return items
        return [
            SpecialOrderItem(
                name=self._title.text().strip(),
                description=self._description.toPlainText().strip(),
                price=f"{self._price.value():.2f}",
                quantity=self._qty.value(),
            )
        ]

    def _find_handling_product(self) -> object | None:
        for product in self._products:
            if str(getattr(product, "name", "") or "").strip().casefold() == _HANDLING_NAME.casefold():
                return product
        return None

    def _is_selected_product(self, product: object) -> bool:
        product_id = str(getattr(product, "id", "") or "").strip()
        product_sku = str(getattr(product, "sku", "") or "").strip()
        for selected in self._selected_products:
            if self._same_product(selected, product_id=product_id, product_sku=product_sku):
                return True
        return False

    @staticmethod
    def _same_product(selected: object, *, product_id: str, product_sku: str) -> bool:
        selected_id = str(getattr(selected, "id", "") or "").strip()
        selected_sku = str(getattr(selected, "sku", "") or "").strip()
        if product_id and selected_id and product_id == selected_id:
            return True
        if product_sku and selected_sku and product_sku == selected_sku:
            return True
        return False

    def _payment_link_title(self) -> str:
        names = [str(getattr(product, "name", "") or "").strip() for product in self._selected_products]
        names = [name for name in names if name]
        if not names:
            return "Digital delivery"
        if len(names) == 1:
            return f"Digital delivery: {names[0]}"
        return f"Digital delivery: {len(names)} items"

    def _payment_link_description(self) -> str:
        names = [str(getattr(product, "name", "") or "").strip() for product in self._selected_products]
        names = [name for name in names if name]
        if not names:
            return "Licensed digital delivery."
        return "Licensed digital delivery for: " + "; ".join(names)

    @staticmethod
    def _product_price(product: object) -> float:
        try:
            return float(str(getattr(product, "price", "") or "0").replace(",", "."))
        except ValueError:
            return 0.0

    def _on_link_created(self, payload: object) -> None:
        url = self._https_url(str(payload or ""))
        if url:
            QApplication.clipboard().setText(url)
        self._status.setText(f"Payment Link erstellt: {url}")
        QMessageBox.information(self, "Sonderauftrag", f"Payment Link erstellt und in die Zwischenablage kopiert:\n{url}")

    def _on_link_error(self, exc: Exception) -> None:
        self._status.setText("Fehler")
        QMessageBox.warning(self, "Sonderauftrag", str(exc))

    @staticmethod
    def _https_url(text: str) -> str:
        match = re.search(r"https://\S+", text)
        if not match:
            return ""
        return match.group(0).rstrip(".,;:)]}\"'")
