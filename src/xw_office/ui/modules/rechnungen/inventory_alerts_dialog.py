"""Inventory alert popup used from the RECHNUNGEN toolbar."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from xw_office.services.mailing.service import MailDeliveryService
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.inventory_alert_tasks import InventoryAlertTaskService


class InventoryAlertsDialog(QDialog):
    def __init__(self, container, parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self._inventory: InventoryV2Service = container.resolve(InventoryV2Service)
        self._tasks: InventoryAlertTaskService = container.resolve(InventoryAlertTaskService)
        self._mail: MailDeliveryService = container.resolve(MailDeliveryService)
        self._details = []
        self.setWindowTitle("Lageralarme")
        self.resize(650, 420)
        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._select)
        layout.addWidget(self._list)
        form = QFormLayout()
        self._product = QLabel("—")
        self._stock = QLabel("—")
        self._mode = QLabel("—")
        self._threshold = QSpinBox()
        self._forecast = QLabel("Forecast")
        self._window = QLabel("Datenfenster")
        self._threshold.setRange(0, 1_000_000)
        form.addRow("Produkt / SKU:", self._product)
        form.addRow("Ist-Bestand:", self._stock)
        form.addRow("Alarmbestand:", self._threshold)
        form.addRow("Automatik / Modus:", self._mode)
        form.addRow("Absatz / 3 Monate:", self._forecast)
        form.addRow("Datenfenster:", self._window)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self._save = QPushButton("Alarmbestand speichern")
        self._save.clicked.connect(self._save_threshold)
        self._auto = QPushButton("Automatik verwenden")
        self._auto.clicked.connect(self._use_automatic)
        self._task = QPushButton("Task erzeugen")
        self._task.clicked.connect(self._create_task)
        close = QPushButton("Schließen")
        close.clicked.connect(self.accept)
        buttons.addWidget(self._save)
        buttons.addWidget(self._auto)
        buttons.addWidget(self._task)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        self._details = self._inventory.list_open_alert_details()
        self._list.clear()
        for detail in self._details:
            item = QListWidgetItem(f"{detail.sku} — {detail.title} ({detail.on_hand} / {detail.reorder_point})")
            item.setData(Qt.ItemDataRole.UserRole, str(detail.alert.id))
            self._list.addItem(item)
        if self._details:
            self._list.setCurrentRow(0)
        else:
            self._product.setText("Keine aktiven Lageralarme")
            self._stock.setText("—")
            self._threshold.setValue(0)
            self._forecast.setText("—")
            self._window.setText("—")
            self._mode.setText("—")

    def _select(self, row: int) -> None:
        if row < 0 or row >= len(self._details):
            return
        detail = self._details[row]
        self._product.setText(f"{detail.title} ({detail.sku})")
        self._stock.setText(str(detail.on_hand))
        self._threshold.setValue(detail.reorder_point)
        self._mode.setText(f"{detail.automatic_reorder_point} / {detail.reorder_mode}")
        self._forecast.setText(f"{detail.average_monthly_sales:.2f} Stk/Monat / {detail.three_month_demand} Stk")
        self._window.setText(detail.forecast_window)

    def _current(self):
        row = self._list.currentRow()
        return self._details[row] if 0 <= row < len(self._details) else None

    def _save_threshold(self) -> None:
        detail = self._current()
        if detail is None:
            return
        try:
            self._inventory.update_thresholds(
                variant_id=detail.alert.variant_id,
                location_code=detail.location_code,
                reorder_point=self._threshold.value(),
                reorder_mode="fixed",
            )
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Alarmbestand", str(exc))

    def _use_automatic(self) -> None:
        detail = self._current()
        if detail is None:
            return
        try:
            self._inventory.update_thresholds(
                variant_id=detail.alert.variant_id,
                location_code=detail.location_code,
                reorder_point=detail.automatic_reorder_point,
                automatic_reorder_point=detail.automatic_reorder_point,
                reorder_mode="auto",
            )
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Alarmbestand", str(exc))

    def _create_task(self) -> None:
        detail = self._current()
        if detail is None:
            return
        try:
            result = self._tasks.create_and_send(detail.alert.id, mail_delivery=self._mail)
            if result.status == "sent":
                QMessageBox.information(self, "Task erzeugen", "Task-Mail wurde an todo@xeisworks.at gesendet.")
            else:
                QMessageBox.warning(self, "Task erzeugen", result.error or "Task-Mail konnte nicht gesendet werden.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Task erzeugen", str(exc))


__all__ = ["InventoryAlertsDialog"]
