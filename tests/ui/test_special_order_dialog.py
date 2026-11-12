from __future__ import annotations

from threading import Event

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.services.special_orders import SpecialOrderService
from xw_office.ui.modules.rechnungen.special_order_dialog import SpecialOrderDialog


def test_special_order_service_resolution_runs_off_ui_thread(qtbot) -> None:
    entered = Event()
    release = Event()

    class Service:
        def list_wix_products(self) -> list[object]:
            return []

    def create_service(_container: Container) -> Service:
        entered.set()
        release.wait(2)
        return Service()

    container = Container(AppConfig())
    container.register(SpecialOrderService, create_service)  # type: ignore[arg-type]
    dialog = SpecialOrderDialog(container)
    qtbot.addWidget(dialog)
    heartbeats: list[bool] = []
    QTimer.singleShot(20, lambda: heartbeats.append(True))
    qtbot.waitUntil(entered.is_set, timeout=1000)
    qtbot.waitUntil(lambda: bool(heartbeats), timeout=1000)
    assert dialog._status.text() == "Lade Wix-Produkte..."  # noqa: SLF001
    release.set()
    qtbot.waitUntil(
        lambda: dialog._worker is None and dialog._status.text() == "Wix-Produkte: 0",
        timeout=1000,
    )


def test_payment_link_write_keeps_dialog_open_until_result(qtbot, monkeypatch) -> None:
    entered = Event()
    release = Event()

    class Service:
        def list_wix_products(self) -> list[object]:
            return []

        def create_payment_link(self, **_kwargs: object) -> object:
            entered.set()
            assert release.wait(2)

            class Link:
                url = "https://checkout.example.test/payment/123"

            return Link()

    container = Container(AppConfig())
    container.register(SpecialOrderService, lambda _container: Service())  # type: ignore[arg-type]
    notices: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args: notices.append(args),
    )
    dialog = SpecialOrderDialog(container)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(
        lambda: dialog._worker is None and dialog._status.text().startswith("Wix-Produkte:"),
        timeout=2000,
    )
    dialog._title.setText("Sonderanfertigung")

    dialog._create_link()
    qtbot.waitUntil(entered.is_set, timeout=2000)

    dialog.reject()
    dialog.close()
    assert dialog.isVisible()
    assert dialog._creating_link

    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=2000)

    assert not dialog._creating_link
    assert dialog.isVisible()
    assert "Payment Link erstellt" in dialog._status.text()
    assert len(notices) == 1

    dialog.reject()
    assert not dialog.isVisible()
