"""UI test: DOWNLOAD-LINKS action opens Wix dashboard URL."""
from __future__ import annotations

import threading

from PySide6.QtCore import QTimer

from xw_office.bootstrap import register_default_services
from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.services.sevdesk.invoice_client import InvoiceSummary
from xw_office.services.wix.client import WixOrdersClient
from xw_office.ui.modules.rechnungen.view import RechnungenView


class _FakeWixOrdersClient:
    def __init__(self, url: str) -> None:
        self._url = url

    def resolve_order_dashboard_url(self, reference: str) -> str:
        _ = reference
        return self._url


def _build_container() -> Container:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    return container


def test_download_links_action_opens_url(qtbot: object, monkeypatch: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    summary = InvoiceSummary.model_validate(
        {
            "id": "42",
            "invoiceNumber": "RE-42",
            "order_reference": "10023",
        }
    )

    expected_url = "https://manage.wix.com/dashboard/site/order/abc123"
    fake_wix = _FakeWixOrdersClient(expected_url)

    original_resolve = container.resolve

    def resolve_override(service_type: type):
        if service_type is WixOrdersClient:
            return fake_wix
        return original_resolve(service_type)

    monkeypatch.setattr(container, "resolve", resolve_override)

    called: dict[str, str] = {"url": ""}

    def open_url_spy(qurl):
        called["url"] = qurl.toString()
        return True

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.view.QDesktopServices.openUrl", open_url_spy)

    view._open_wix_download_links(summary)  # noqa: SLF001

    qtbot.waitUntil(lambda: called["url"] == expected_url, timeout=1000)


def test_download_links_resolution_runs_off_thread_and_coalesces_clicks(
    qtbot: object, monkeypatch: object
) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate({"id": "42", "order_reference": "10023"})
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    class BlockingWixClient(_FakeWixOrdersClient):
        def resolve_order_dashboard_url(self, reference: str) -> str:
            nonlocal calls
            calls += 1
            entered.set()
            release.wait(timeout=2)
            return self._url

    fake_wix = BlockingWixClient("https://manage.wix.com/order/abc123")
    original_resolve = container.resolve

    def resolve_override(service_type: type):
        if service_type is WixOrdersClient:
            return fake_wix
        return original_resolve(service_type)

    monkeypatch.setattr(container, "resolve", resolve_override)
    opened: list[str] = []
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    heartbeat: list[bool] = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))

    view._open_wix_download_links(summary)  # noqa: SLF001
    assert entered.wait(timeout=1)
    view._open_wix_download_links(summary)  # noqa: SLF001
    qtbot.waitUntil(lambda: bool(heartbeat), timeout=500)
    assert calls == 1

    release.set()
    qtbot.waitUntil(lambda: bool(opened), timeout=1000)
    assert opened == ["https://manage.wix.com/order/abc123"]
