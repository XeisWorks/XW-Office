"""The desktop must honor the Product-Hub inventory cutover flag."""
from __future__ import annotations

from collections.abc import Callable

from xw_office.bootstrap import register_default_services
from xw_office.core.config import AppConfig, ProductHubSection
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.product_hub.invoice_inventory import InvoiceInventoryBookingService


class _ContainerProbe:
    def __init__(self, *, master_enabled: bool) -> None:
        self.config = AppConfig(
            database_url="sqlite:///:memory:",
            product_hub=ProductHubSection(inventory_master_enabled=master_enabled),
        )
        self.factories: dict[type[object], Callable[..., object]] = {}
        self.resolved: list[type[object]] = []

    def register(self, service_type: type[object], factory: Callable[..., object]) -> None:
        self.factories[service_type] = factory

    def resolve(self, service_type: type[object]) -> object:
        self.resolved.append(service_type)
        return object()


def test_invoice_inventory_booking_only_uses_the_hub_after_master_cutover() -> None:
    for master_enabled in (False, True):
        container = _ContainerProbe(master_enabled=master_enabled)
        register_default_services(container)  # type: ignore[arg-type]

        service = container.factories[InvoiceProcessingService](container)

        assert isinstance(service, InvoiceProcessingService)
        assert service.invoice_inventory_enabled is master_enabled
        assert (
            InvoiceInventoryBookingService in container.resolved
        ) is master_enabled
