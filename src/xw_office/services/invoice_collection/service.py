"""Application service wiring local connections to factories and orchestrator."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.services.invoice_collection.domain import DateRange, ProviderConnection
from xw_office.services.invoice_collection.errors import InvoiceCollectionError, InvoiceErrorCode
from xw_office.services.invoice_collection.factories import ConnectorFactoryRegistry
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.orchestrator import (
    CollectionOrchestrator,
    CollectionSummary,
)
from xw_office.services.invoice_collection.pipeline import DocumentPipeline
from xw_office.services.invoice_collection.ports import CancelToken
from xw_office.services.invoice_collection.registry import ProviderCatalog
from xw_office.services.invoice_collection.sinks.onedrive_local import OneDriveLocalSink


@dataclass(frozen=True)
class ConnectionRouteIssue:
    connection_id: str
    route_key: str
    message: str


@dataclass(frozen=True)
class CollectionRun:
    summary: CollectionSummary
    issues: tuple[ConnectionRouteIssue, ...] = ()


class InvoiceCollectionService:
    """Compose repository, factories, pipeline and orchestrator without provider branches."""

    def __init__(
        self,
        *,
        connections: ConnectionRepository,
        factories: ConnectorFactoryRegistry,
        target_root: Path,
        journal: InvoiceJournal | None = None,
        catalog: ProviderCatalog | None = None,
    ) -> None:
        self.connections = connections
        self.factories = factories
        self.target_root = target_root
        self.journal = journal or InvoiceJournal()
        self.catalog = catalog

    def active_connections(self) -> list[ProviderConnection]:
        return self.connections.list_enabled()

    def collect_active(
        self,
        *,
        cancel: CancelToken | None = None,
        max_workers: int = 2,
        period: DateRange | None = None,
    ) -> CollectionRun:
        sink = OneDriveLocalSink(self.target_root)
        pipeline = DocumentPipeline(sink=sink, journal=self.journal)
        orchestrator = CollectionOrchestrator(
            pipeline, workspace_root=None, max_workers=max_workers
        )
        connectors = []
        issues: list[ConnectionRouteIssue] = []
        for connection in self.active_connections():
            for route in connection.route_settings:
                if not route.enabled:
                    continue
                try:
                    if self.catalog is not None:
                        manifest = self.catalog.route(connection.provider_id, route.route_key)
                        if manifest is None:
                            raise InvoiceCollectionError(
                                code=InvoiceErrorCode.CONFIGURATION_ERROR,
                                message="Connection ist nicht mehr im Provider-Katalog vorhanden",
                            )
                        if manifest.maturity != "verified":
                            raise InvoiceCollectionError(
                                code=InvoiceErrorCode.UNSUPPORTED_ACCOUNT,
                                message="Abrufroute ist nicht live verifiziert",
                            )
                    connector_key = str(route.options.get("connector") or route.route_key)
                    connectors.append(
                        self.factories.create(connector_key, connection, route, period)
                    )
                except Exception as exc:  # noqa: BLE001 - route-local setup issue
                    message = (
                        f"{exc.code.value}: {exc}"
                        if isinstance(exc, InvoiceCollectionError)
                        else f"INTERNAL_ERROR: {type(exc).__name__}"
                    )
                    issues.append(
                        ConnectionRouteIssue(
                            connection_id=str(connection.connection_id),
                            route_key=route.route_key,
                            message=message,
                        )
                    )
        return CollectionRun(
            summary=orchestrator.collect(connectors, cancel=cancel),
            issues=tuple(issues),
        )
