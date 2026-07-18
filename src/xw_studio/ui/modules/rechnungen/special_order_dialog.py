"""Dialog for creating special-order Wix payment links."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
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
)

from xw_studio.core.container import Container
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.special_orders import SpecialOrderItem, SpecialOrderService

_HANDLING_NAME = "Digital Delivery Handling"


class SpecialOrderDialog(QDialog):
    """Create one-off physical/digital special-order payment links."""

    def __init__(self, container: Container, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._container = container
        self._service: SpecialOrderService = container.resolve(SpecialOrderService)
        self._products: list[object] = []
        self._worker: BackgroundWorker | None = None
        self._build_ui()
        QTimer.singleShot(0, self._load_products)

    def _build_ui(self) -> None:
        self.setWindowTitle("Sonderauftrag / Payment Link")
        self.setMinimumSize(760, 680)
        root = QVBoxLayout(self)

        form = QFormLayout()
        self._mode = QComboBox()
        self._mode.addItem("Physische Sonderanfertigung", "physical_custom")
        self._mode.addItem("Digitale Sonderanfertigung", "digital_custom")
        self._mode.addItem("Bestehende Noten digital liefern", "digital_sheet_music")
        self._mode.currentIndexChanged.connect(self._update_mode)
        form.addRow("Art:", self._mode)

        self._email = QLineEdit()
        form.addRow("E-Mail:", self._email)
        self._first_name = QLineEdit()
        form.addRow("Vorname:", self._first_name)
        self._last_name = QLineEdit()
        form.addRow("Nachname:", self._last_name)
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
        root.addLayout(form)

        self._product_label = QLabel("Wix-Produkte fuer digitale Noten:")
        root.addWidget(self._product_label)
        self._product_filter = QLineEdit()
        self._product_filter.setPlaceholderText("SKU oder Name suchen")
        self._product_filter.textChanged.connect(self._filter_products)
        root.addWidget(self._product_filter)
        self._product_list = QListWidget()
        self._product_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._product_list.itemSelectionChanged.connect(self._sync_price_from_selection)
        root.addWidget(self._product_list, stretch=1)

        row = QHBoxLayout()
        self._status = QLabel("-")
        row.addWidget(self._status, stretch=1)
        self._create_btn = QPushButton("Payment Link erstellen + Mail vorbereiten")
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
            if query and query not in f"{sku} {name}".casefold():
                continue
            price = str(getattr(product, "price", "") or "")
            item = QListWidgetItem(f"{sku} | {name} | {price} EUR")
            item.setData(256, product)
            self._product_list.addItem(item)

    def _update_mode(self) -> None:
        is_digital_sheet = self._mode.currentData() == "digital_sheet_music"
        self._product_label.setVisible(is_digital_sheet)
        self._product_filter.setVisible(is_digital_sheet)
        self._product_list.setVisible(is_digital_sheet)
        self._price.setEnabled(not is_digital_sheet)
        self._qty.setEnabled(not is_digital_sheet)

    def _sync_price_from_selection(self) -> None:
        if self._mode.currentData() != "digital_sheet_music":
            return
        selected = self._product_list.selectedItems()
        total = 0.0
        for item in selected:
            product = item.data(256)
            try:
                total += float(str(getattr(product, "price", "") or "0").replace(",", "."))
            except ValueError:
                pass
        if total > 0:
            self._price.setValue(total)

    def _create_link(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        mode = str(self._mode.currentData())
        title = self._title.text().strip()
        email = self._email.text().strip()
        first_name = self._first_name.text().strip()
        last_name = self._last_name.text().strip()
        if not title or not email:
            QMessageBox.warning(self, "Sonderauftrag", "Titel und E-Mail sind Pflicht.")
            return
        try:
            items = self._build_items(mode)
        except RuntimeError as exc:
            QMessageBox.warning(self, "Sonderauftrag", str(exc))
            return

        def job() -> str:
            link = self._service.create_payment_link(
                mode=mode,  # type: ignore[arg-type]
                title=title,
                description=self._description.toPlainText(),
                items=items,
                customer_email=email,
                customer_first_name=first_name,
                customer_last_name=last_name,
            )
            self._service.open_link_mail_draft(
                to_email=email,
                first_name=first_name,
                title=title,
                link=link,
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
            for selected in self._product_list.selectedItems():
                product = selected.data(256)
                if str(getattr(product, "name", "") or "").strip().casefold() == _HANDLING_NAME.casefold():
                    continue
                price = str(getattr(product, "price", "") or "").replace(",", ".")
                items.append(
                    SpecialOrderItem(
                        type="CATALOG",
                        catalog_item_id=str(getattr(product, "id", "") or ""),
                        sku=str(getattr(product, "sku", "") or ""),
                        name=str(getattr(product, "name", "") or ""),
                        price=price,
                    )
                )
            if not items:
                raise RuntimeError("Bitte mindestens ein Wix-Produkt auswaehlen.")
            handling = self._find_handling_product()
            if handling is None:
                raise RuntimeError("Wix-Produkt 'Digital Delivery Handling' wurde nicht gefunden.")
            items.append(
                SpecialOrderItem(
                    type="CATALOG",
                    catalog_item_id=str(getattr(handling, "id", "") or ""),
                    sku=str(getattr(handling, "sku", "") or ""),
                    name=str(getattr(handling, "name", "") or _HANDLING_NAME),
                    price=str(getattr(handling, "price", "") or "0").replace(",", "."),
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

    def _on_link_created(self, payload: object) -> None:
        self._status.setText(f"Payment Link erstellt: {payload}")
        QMessageBox.information(self, "Sonderauftrag", f"Payment Link erstellt und Outlook-Entwurf geoeffnet:\n{payload}")

    def _on_link_error(self, exc: Exception) -> None:
        self._status.setText("Fehler")
        QMessageBox.warning(self, "Sonderauftrag", str(exc))
