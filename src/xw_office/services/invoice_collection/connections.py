"""Local, secret-free ProviderConnection repository."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import UUID
import hashlib

from xw_office.core.app_paths import invoice_collection_dir
from xw_office.services.invoice_collection.domain import (
    ProviderConnection,
    RouteSettings,
    TenantId,
)


@dataclass(frozen=True)
class InvalidConnectionRecord:
    """Safe reference to an enabled row that cannot be decoded as a connection."""

    connection_id: str
    error_type: str


class ConnectionRepository:
    """Persist connection metadata; secret values remain in the SecretStore/keyring."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (invoice_collection_dir() / "journal" / "invoice_collection.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_connections (
                    connection_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    account_alias TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    routes_json TEXT NOT NULL
                )
                """
            )

    def save(self, connection_value: ProviderConnection) -> None:
        routes = [
            {
                "route_key": route.route_key,
                "enabled": route.enabled,
                "priority": route.priority,
                "options": dict(route.options),
                "secret_ref": route.secret_ref,
            }
            for route in connection_value.route_settings
        ]
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_connections(
                    connection_id, provider_id, tenant_id, account_alias, enabled, routes_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id) DO UPDATE SET
                    provider_id=excluded.provider_id,
                    tenant_id=excluded.tenant_id,
                    account_alias=excluded.account_alias,
                    enabled=excluded.enabled,
                    routes_json=excluded.routes_json
                """,
                (
                    str(connection_value.connection_id),
                    connection_value.provider_id,
                    connection_value.tenant_id.value,
                    connection_value.account_alias,
                    int(connection_value.enabled),
                    json.dumps(routes, ensure_ascii=False, separators=(",", ":")),
                ),
            )

    def list_enabled(self) -> list[ProviderConnection]:
        connections, issues = self.list_enabled_with_issues()
        if issues:
            raise ValueError("one or more saved provider connections are invalid")
        return connections

    def list_enabled_with_issues(
        self,
    ) -> tuple[list[ProviderConnection], list[InvalidConnectionRecord]]:
        """Load valid rows and isolate malformed legacy rows for per-record reporting."""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM provider_connections "
                "WHERE enabled=1 ORDER BY provider_id, account_alias"
            ).fetchall()
        valid: list[ProviderConnection] = []
        issues: list[InvalidConnectionRecord] = []
        for row in rows:
            try:
                valid.append(_from_row(row))
            except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raw_id = str(row["connection_id"] or "")
                try:
                    safe_id = str(UUID(raw_id))
                except ValueError:
                    digest = hashlib.sha256(raw_id.encode("utf-8", errors="replace")).hexdigest()
                    safe_id = f"invalid-{digest[:12]}"
                issues.append(
                    InvalidConnectionRecord(connection_id=safe_id, error_type=type(exc).__name__)
                )
        return valid, issues


def _from_row(row: sqlite3.Row) -> ProviderConnection:
    raw_routes = json.loads(str(row["routes_json"] or "[]"))
    routes = tuple(
        RouteSettings(
            route_key=str(item.get("route_key") or ""),
            enabled=bool(item.get("enabled", True)),
            priority=int(item.get("priority") or 100),
            options={str(key): str(value) for key, value in (item.get("options") or {}).items()},
            secret_ref=str(item.get("secret_ref")) if item.get("secret_ref") else None,
        )
        for item in raw_routes
        if isinstance(item, dict) and str(item.get("route_key") or "").strip()
    )
    return ProviderConnection(
        connection_id=UUID(str(row["connection_id"])),
        provider_id=str(row["provider_id"]),
        tenant_id=TenantId(str(row["tenant_id"])),
        account_alias=str(row["account_alias"]),
        enabled=bool(row["enabled"]),
        route_settings=routes,
    )
