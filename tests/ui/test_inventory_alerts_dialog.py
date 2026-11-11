from __future__ import annotations

from threading import Event
from types import SimpleNamespace

from PySide6.QtCore import QTimer

from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.inventory_alert_tasks import InventoryAlertTaskService
from xw_office.services.mailing.service import MailDeliveryService
from xw_office.ui.modules.rechnungen.inventory_alerts_dialog import InventoryAlertsDialog


class _AlertsContainer:
    def __init__(self, inventory: object) -> None:
        self.inventory = inventory

    def resolve(self, service_type: object) -> object:
        if service_type is InventoryV2Service:
            return self.inventory
        if service_type is InventoryAlertTaskService:
            return SimpleNamespace()
        if service_type is MailDeliveryService:
            return SimpleNamespace()
        raise KeyError(service_type)


def test_inventory_alert_load_and_save_leave_event_loop_responsive(qtbot) -> None:
    load_started = Event()
    save_started = Event()
    release = Event()
    saved: list[dict[str, object]] = []
    load_calls = 0
    detail = SimpleNamespace(
        alert=SimpleNamespace(id="alert-1", variant_id="variant-1"),
        sku="XW-TEST",
        title="Test",
        location_code="MAIN",
        on_hand=2,
        reorder_point=4,
        automatic_reorder_point=5,
        reorder_mode="fixed",
        average_monthly_sales=1.0,
        three_month_demand=3,
        forecast_window="90d",
    )

    class Inventory:
        def list_open_alert_details(self):
            nonlocal load_calls
            load_calls += 1
            load_started.set()
            release.wait(2)
            return [detail]

        def update_thresholds(self, **kwargs):
            save_started.set()
            release.wait(2)
            saved.append(kwargs)
            detail.reorder_point = kwargs["reorder_point"]

    dialog = InventoryAlertsDialog(_AlertsContainer(Inventory()))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    heartbeats: list[bool] = []
    QTimer.singleShot(20, lambda: heartbeats.append(True))
    qtbot.waitUntil(load_started.is_set, timeout=1000)
    qtbot.waitUntil(lambda: bool(heartbeats), timeout=1000)
    assert dialog._list.isEnabled() is False  # noqa: SLF001

    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
    dialog._threshold.setValue(7)  # noqa: SLF001
    release.clear()
    dialog._save_threshold()  # noqa: SLF001
    qtbot.waitUntil(save_started.is_set, timeout=1000)
    assert saved == []
    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
    assert saved == [
        {
            "variant_id": "variant-1",
            "location_code": "MAIN",
            "reorder_point": 7,
            "reorder_mode": "fixed",
        }
    ]
    qtbot.waitUntil(lambda: load_calls == 2, timeout=1000)
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
    assert dialog._threshold.value() == 7  # noqa: SLF001


def test_threshold_change_notifies_parent_immediately(qtbot) -> None:
    detail = SimpleNamespace(
        alert=SimpleNamespace(id="alert-2", variant_id="variant-2"),
        sku="XW-TEST-2", title="Test 2", location_code="MAIN", on_hand=1,
        reorder_point=3, automatic_reorder_point=4, reorder_mode="fixed",
        average_monthly_sales=1.0, three_month_demand=3, forecast_window="90d",
    )
    changed: list[bool] = []

    class Inventory:
        def list_open_alert_details(self):
            return [detail]

        def update_thresholds(self, **kwargs):
            detail.reorder_point = kwargs["reorder_point"]

    dialog = InventoryAlertsDialog(_AlertsContainer(Inventory()))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.alerts_changed.connect(lambda: changed.append(True))
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
    dialog._threshold.setValue(5)  # noqa: SLF001
    dialog._save_threshold()  # noqa: SLF001
    qtbot.waitUntil(lambda: bool(changed), timeout=1000)
    assert changed == [True]
