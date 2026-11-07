"""Explicit connector-factory registry; YAML never controls imports."""
from __future__ import annotations

from collections.abc import Callable

from xw_office.services.invoice_collection.domain import ProviderConnection, RouteSettings
from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.ports import InvoiceConnector


ConnectorFactory = Callable[[ProviderConnection, RouteSettings], InvoiceConnector]


class ConnectorFactoryRegistry:
    """Map known connector keys to code-owned factories."""

    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}

    def register(self, key: str, factory: ConnectorFactory) -> None:
        normalized = str(key or "").strip()
        if not normalized or "__" in normalized or "." in normalized:
            raise ValueError("connector key must be a simple, non-importable name")
        if normalized in self._factories:
            raise ValueError(f"connector factory already registered: {normalized}")
        self._factories[normalized] = factory

    def create(
        self,
        key: str,
        connection: ProviderConnection,
        settings: RouteSettings,
    ) -> InvoiceConnector:
        try:
            factory = self._factories[key]
        except KeyError as exc:
            raise InvoiceCollectionError(
                InvoiceErrorCode.CONFIGURATION_ERROR,
                f"Keine Connector-Factory für aktive Route: {key}",
            ) from exc
        return factory(connection, settings)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
