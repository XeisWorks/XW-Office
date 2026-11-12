"""Inventory alert popup used from the RECHNUNGEN toolbar."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
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
    QWidget,
)

from xw_office.services.mailing.service import MailDeliveryService
from xw_office.services.product_hub.inventory import InventoryAlertDetail, InventoryV2Service
from xw_office.services.product_hub.inventory_alert_tasks import InventoryAlertTaskService
from xw_office.core.worker import BackgroundWorker
from shiboken6 import isValid


class InventoryAlertsDialog(QDialog):
    alerts_changed = Signal()

    def __init__(self, container: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._details: list[InventoryAlertDetail] = []
        self._worker: BackgroundWorker | None = None
        self._write_worker: BackgroundWorker | None = None
        self._closing = False
        self._refresh_pending = False
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
        self._target = QLabel("Zielbestand / Bestellmenge")
        self._threshold.setRange(0, 1_000_000)
        form.addRow("Produkt / SKU:", self._product)
        form.addRow("Ist-Bestand:", self._stock)
        form.addRow("Alarmbestand:", self._threshold)
        form.addRow("Automatik / Modus:", self._mode)
        form.addRow("Absatz / 3 Monate:", self._forecast)
        form.addRow("Datenfenster:", self._window)
        form.addRow("Ziel / Bestellmenge:", self._target)
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

    def accept(self) -> None:
        if self._write_worker is not None:
            return
        self._closing = True
        super().accept()

    def reject(self) -> None:
        if self._write_worker is not None:
            return
        self._closing = True
        super().reject()

    def refresh(self) -> None:
        if self._closing or not isValid(self):
            return
        if self._worker is not None and self._worker.isRunning():
            self._refresh_pending = True
            return
        self._set_busy(True)
        container = self._container

        def job() -> list[InventoryAlertDetail]:
            inventory: InventoryV2Service = container.resolve(InventoryV2Service)
            return inventory.list_open_alert_details()

        worker = BackgroundWorker(job)
        self._worker = worker
        worker.signals.result.connect(self._on_details_loaded)
        worker.signals.error.connect(self._on_refresh_error)
        worker.signals.finished.connect(lambda current=worker: self._worker_finished(current))
        worker.start()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._write_worker is not None:
            event.ignore()
            return
        self._closing = True
        super().closeEvent(event)

    def _on_details_loaded(self, result: object) -> None:
        if self._closing or not isValid(self):
            return
        self._details = list(result) if isinstance(result, list) else []
        self._list.clear()
        for detail in self._details:
            item = QListWidgetItem(
                f"{detail.sku} ? {detail.title} ({detail.on_hand} / {detail.reorder_point})"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(detail.alert.id))
            self._list.addItem(item)
        if self._details:
            self._list.setCurrentRow(0)
        else:
            self._product.setText("Keine aktiven Lageralarme")
            self._stock.setText("?")
            self._threshold.setValue(0)
            self._forecast.setText("?")
            self._window.setText("?")
            self._mode.setText("?")
            self._target.setText("?")

    def _on_refresh_error(self, exc: Exception) -> None:
        if not self._closing and isValid(self):
            QMessageBox.warning(self, "Lageralarme", str(exc))

    def _worker_finished(self, worker: BackgroundWorker) -> None:
        is_current = self._worker is worker
        if is_current:
            self._worker = None
        if self._write_worker is worker:
            self._write_worker = None
        if is_current and not self._closing and isValid(self):
            self._set_busy(False)
            if self._refresh_pending:
                self._refresh_pending = False
                QTimer.singleShot(0, self.refresh)

    def _set_busy(self, busy: bool) -> None:
        for button in (self._save, self._auto, self._task):
            button.setEnabled(not busy and self._current() is not None)
        self._list.setEnabled(not busy)

    def _run_action(
        self,
        job: Callable[[], Any],
        on_result: Callable[[object], None],
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        worker = BackgroundWorker(job)
        self._worker = worker
        self._write_worker = worker
        worker.signals.result.connect(
            lambda result: on_result(result) if not self._closing and isValid(self) else None
        )
        worker.signals.error.connect(self._on_refresh_error)
        worker.signals.finished.connect(lambda current=worker: self._worker_finished(current))
        worker.start()

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
        self._target.setText(
            f"{getattr(detail, 'target_stock', detail.reorder_point)} / "
            f"{getattr(detail, 'suggested_order_quantity', max(0, detail.reorder_point - detail.on_hand))} Stk"
        )

    def _current(self) -> InventoryAlertDetail | None:
        row = self._list.currentRow()
        return self._details[row] if 0 <= row < len(self._details) else None

    def _save_threshold(self) -> None:
        detail = self._current()
        if detail is None:
            return
        variant_id = detail.alert.variant_id
        location_code = detail.location_code
        reorder_point = self._threshold.value()
        container = self._container
        self._run_action(
            lambda: container.resolve(InventoryV2Service).update_thresholds(
                variant_id=variant_id, location_code=location_code,
                reorder_point=reorder_point, reorder_mode="fixed",
            ),
            self._threshold_change_finished,
        )

    def _use_automatic(self) -> None:
        detail = self._current()
        if detail is None:
            return
        variant_id = detail.alert.variant_id
        location_code = detail.location_code
        automatic_point = detail.automatic_reorder_point
        container = self._container
        self._run_action(
            lambda: container.resolve(InventoryV2Service).update_thresholds(
                variant_id=variant_id,
                location_code=location_code,
                reorder_point=automatic_point,
                automatic_reorder_point=automatic_point,
                reorder_mode="auto",
            ),
            self._threshold_change_finished,
        )

    def _threshold_change_finished(self, _result: object) -> None:
        self.alerts_changed.emit()
        self.refresh()

    def _create_task(self) -> None:
        detail = self._current()
        if detail is None:
            return
        alert_id = detail.alert.id

        def show_result(result: object) -> None:
            status = str(getattr(result, "status", ""))
            if status == "sent":
                QMessageBox.information(
                    self, "Task erzeugen", "Task-Mail wurde an todo@xeisworks.at gesendet."
                )
            elif status == "pending":
                QMessageBox.information(
                    self, "Task erzeugen", "Die Task-Mail wird bereits versendet."
                )
            elif status == "unknown":
                QMessageBox.warning(
                    self,
                    "Task erzeugen",
                    "Der Versandstatus ist unklar. Bitte zuerst den Mailversand pruefen. "
                    "Es wird keine weitere Mail automatisch versendet.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Task erzeugen",
                    str(getattr(result, "error", "")) or "Task-Mail konnte nicht gesendet werden.",
                )

        container = self._container

        def job() -> object:
            tasks: InventoryAlertTaskService = container.resolve(InventoryAlertTaskService)
            mail: MailDeliveryService = container.resolve(MailDeliveryService)
            return tasks.create_and_send(alert_id, mail_delivery=mail)

        self._run_action(job, show_result)

__all__ = ["InventoryAlertsDialog"]
