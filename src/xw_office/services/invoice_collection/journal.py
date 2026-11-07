"""Small local SQLite journal for idempotency and provenance."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock

from xw_office.core.app_paths import invoice_collection_dir
from xw_office.services.invoice_collection.domain import (
    SinkReceipt,
    ValidatedDocument,
)


class InvoiceJournal:
    """A local metadata journal; it never stores document bytes or secret values."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (invoice_collection_dir() / "journal" / "invoice_collection.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    route_key TEXT NOT NULL,
                    external_id TEXT,
                    sha256 TEXT NOT NULL,
                    sink_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    sync_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (tenant_id, sink_id, sha256)
                );
                CREATE INDEX IF NOT EXISTS idx_documents_external
                    ON documents (connection_id, route_key, external_id);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', '1')"
            )

    def has_hash(self, *, tenant_id: str, sink_id: str, sha256: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM documents WHERE tenant_id=? AND sink_id=? AND sha256=? LIMIT 1",
                (tenant_id, sink_id, sha256),
            ).fetchone()
            return row is not None

    def has_external_id(
        self,
        *,
        connection_id: str,
        route_key: str,
        external_id: str,
    ) -> tuple[str, str] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT sha256, outcome FROM documents "
                "WHERE connection_id=? AND route_key=? AND external_id=? LIMIT 1",
                (connection_id, route_key, external_id),
            ).fetchone()
            return (str(row["sha256"]), str(row["outcome"])) if row else None

    def record_document(
        self,
        *,
        document: ValidatedDocument,
        sink_id: str,
        receipt: SinkReceipt,
    ) -> None:
        candidate = document.candidate
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO documents(
                    document_id, tenant_id, connection_id, provider_id, route_key,
                    external_id, sha256, sink_id, relative_path, outcome, sync_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{candidate.connection.connection_id}:{candidate.source_id}",
                    candidate.connection.tenant_id.value,
                    str(candidate.connection.connection_id),
                    candidate.connection.provider_id,
                    candidate.route_key,
                    candidate.external_id,
                    document.sha256,
                    sink_id,
                    document.relative_path.as_posix(),
                    receipt.outcome.value,
                    receipt.sync_status.value,
                    document.validated_at.isoformat(),
                ),
            )
