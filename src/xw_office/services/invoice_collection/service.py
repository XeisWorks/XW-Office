"""Application service wiring local connections to factories and orchestrator."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.services.invoice_collection.domain import DateRange, ProviderConnection, RunStatus
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
    provider_id: str | None = None
    tenant_id: str | None = None
    account_alias: str | None = None


@dataclass(frozen=True)
class CollectionRun:
    summary: CollectionSummary
    issues: tuple[ConnectionRouteIssue, ...] = ()
    run_id: str | None = None
    resumed: bool = False
    status: RunStatus = RunStatus.IDLE
    period: DateRange | None = None
    connection_ids: tuple[str, ...] = ()


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
        active_connections = self.active_connections()
        fingerprints = {
            str(connection.connection_id): _connection_fingerprint(connection)
            for connection in active_connections
        }
        run_id, resumed = self.journal.begin_or_resume_run(
            period=period,
            target_fingerprint=_target_fingerprint(self.target_root),
            connection_fingerprints=fingerprints,
        )
        sink = OneDriveLocalSink(self.target_root)
        pipeline = DocumentPipeline(sink=sink, journal=self.journal, run_id=run_id)
        orchestrator = CollectionOrchestrator(
            pipeline,
            workspace_root=None,
            max_workers=max_workers,
            journal=self.journal,
            run_id=run_id,
        )
        connectors = []
        issues: list[ConnectionRouteIssue] = []
        route_context: dict[tuple[str, str], ProviderConnection] = {}
        for connection in active_connections:
            for route in connection.route_settings:
                if not route.enabled:
                    continue
                route_identity = (str(connection.connection_id), route.route_key)
                route_context[route_identity] = connection
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
                            provider_id=connection.provider_id,
                            tenant_id=connection.tenant_id.value,
                            account_alias=connection.account_alias,
                        )
                    )
        summary = orchestrator.collect(connectors, cancel=cancel)
        issue_map = {(issue.connection_id, issue.route_key): issue for issue in issues}
        for route_identity, connection in route_context.items():
            route_items = [
                item
                for item in summary.items
                if item.connection_id == route_identity[0] and item.route_key == route_identity[1]
            ]
            issue = issue_map.get(route_identity)
            if summary.cancelled:
                status = "CANCELLED"
                error_code = None
            elif issue is not None:
                status = _error_route_status(issue.message)
                error_code = issue.message.split(":", 1)[0]
            elif any(item.error for item in route_items):
                status = "PARTIAL" if any(item.outcome for item in route_items) else "FAILED"
                error_code = next(
                    (item.error.split(":", 1)[0] for item in route_items if item.error), None
                )
            elif route_items and all(item.outcome is None for item in route_items):
                status = "NO_DOCUMENTS"
                error_code = None
            else:
                status = "SUCCEEDED"
                error_code = None
            self.journal.record_route_status(
                run_id=run_id,
                connection_id=route_identity[0],
                route_key=route_identity[1],
                status=status,
                error_code=error_code,
            )

        has_errors = bool(issues) or any(item.error for item in summary.items)
        if summary.cancelled:
            run_status = RunStatus.CANCELLED
        elif not route_context:
            run_status = RunStatus.FAILED
        elif has_errors:
            completed_route_exists = any(
                route_identity not in issue_map for route_identity in route_context
            )
            run_status = (
                RunStatus.PARTIAL
                if any(item.outcome is not None for item in summary.items)
                or completed_route_exists
                else RunStatus.FAILED
            )
        else:
            run_status = RunStatus.SUCCEEDED
        self.journal.finish_run(run_id=run_id, status=run_status)
        return CollectionRun(
            summary=summary,
            issues=tuple(issues),
            run_id=run_id,
            resumed=resumed,
            status=run_status,
            period=period,
            connection_ids=tuple(fingerprints),
        )


def _connection_fingerprint(connection: ProviderConnection) -> str:
    payload = {
        "provider_id": connection.provider_id,
        "tenant_id": connection.tenant_id.value,
        "account_alias": connection.account_alias,
        "enabled": connection.enabled,
        "routes": [
            {
                "route_key": route.route_key,
                "enabled": route.enabled,
                "priority": route.priority,
                "options": dict(route.options),
                "secret_ref": route.secret_ref,
            }
            for route in connection.route_settings
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _target_fingerprint(path: Path) -> str:
    normalized = str(path.expanduser().resolve(strict=False)).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _error_route_status(message: str) -> str:
    code = message.split(":", 1)[0]
    if code in {"AUTH_REQUIRED", "CONSENT_REQUIRED", "NEEDS_LOGIN", "NEEDS_2FA"}:
        return "WAITING_FOR_USER"
    if code in {"POLICY_BLOCKED", "UNSUPPORTED_ACCOUNT"}:
        return "BLOCKED"
    return "FAILED"
