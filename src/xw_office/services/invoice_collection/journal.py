"""Small local SQLite journal for idempotency and provenance."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
import hashlib
import json
import sqlite3
from pathlib import Path
from threading import RLock
from uuid import uuid4

from xw_office.core.app_paths import invoice_collection_dir
from xw_office.services.invoice_collection.domain import (
    DateRange,
    RunStatus,
    SinkReceipt,
    ValidatedDocument,
)


@dataclass(frozen=True)
class DocumentProvenance:
    """Non-sensitive source attribution; source identifiers are one-way fingerprints."""

    connection_id: str
    provider_id: str
    route_key: str
    source_id_hash: str
    external_id_hash: str | None


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
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            version_row = connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            if version_row is not None:
                try:
                    current_version = int(version_row["value"])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("invoice journal schema version is invalid") from exc
                if current_version > 3:
                    raise RuntimeError(
                        f"invoice journal schema {current_version} is newer than supported schema 3"
                    )
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
                CREATE TABLE IF NOT EXISTS document_provenance (
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    connection_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    route_key TEXT NOT NULL,
                    source_id_hash TEXT NOT NULL,
                    external_id_hash TEXT,
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY (document_id, connection_id, route_key, source_id_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_document_provenance_external
                    ON document_provenance (connection_id, route_key, external_id_hash);
                CREATE TABLE IF NOT EXISTS collection_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    period_start TEXT,
                    period_end TEXT,
                    target_fingerprint TEXT NOT NULL,
                    connection_fingerprints_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_collection_runs_status_updated
                    ON collection_runs (status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS collection_run_routes (
                    run_id TEXT NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
                    connection_id TEXT NOT NULL,
                    route_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, connection_id, route_key)
                );
                CREATE TABLE IF NOT EXISTS collection_checkpoints (
                    run_id TEXT NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
                    connection_id TEXT NOT NULL,
                    route_key TEXT NOT NULL,
                    candidate_hash TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, connection_id, route_key, candidate_hash)
                );
                CREATE TABLE IF NOT EXISTS collection_run_documents (
                    run_id TEXT NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL REFERENCES documents(document_id),
                    PRIMARY KEY (run_id, document_id)
                );
                """
            )
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('schema_version', '3') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )

    def begin_or_resume_run(
        self,
        *,
        period: DateRange | None,
        target_fingerprint: str,
        connection_fingerprints: dict[str, str],
    ) -> tuple[str, bool]:
        """Start a run or resume the newest incomplete run with the exact same context."""
        now = _now()
        connections_json = json.dumps(
            connection_fingerprints, sort_keys=True, separators=(",", ":")
        )
        start = period.start.isoformat() if period else None
        end = period.end.isoformat() if period else None
        resumable = (
            RunStatus.RUNNING.value,
            RunStatus.PARTIAL.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        )
        with self._lock, self._connect() as connection:
            placeholders = ",".join("?" for _ in resumable)
            row = connection.execute(
                f"SELECT run_id FROM collection_runs WHERE status IN ({placeholders}) "
                "AND period_start IS ? AND period_end IS ? AND target_fingerprint=? "
                "AND connection_fingerprints_json=? ORDER BY updated_at DESC LIMIT 1",
                (*resumable, start, end, target_fingerprint, connections_json),
            ).fetchone()
            if row is not None:
                run_id = str(row["run_id"])
                connection.execute(
                    "UPDATE collection_runs SET status=?, updated_at=?, completed_at=NULL "
                    "WHERE run_id=?",
                    (RunStatus.RUNNING.value, now, run_id),
                )
                return run_id, True

            run_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO collection_runs(
                    run_id, status, period_start, period_end, target_fingerprint,
                    connection_fingerprints_json, started_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    run_id,
                    RunStatus.RUNNING.value,
                    start,
                    end,
                    target_fingerprint,
                    connections_json,
                    now,
                    now,
                ),
            )
            return run_id, False

    def record_route_status(
        self,
        *,
        run_id: str,
        connection_id: str,
        route_key: str,
        status: str,
        error_code: str | None = None,
    ) -> None:
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO collection_run_routes(
                    run_id, connection_id, route_key, status, error_code, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, connection_id, route_key) DO UPDATE SET
                    status=excluded.status, error_code=excluded.error_code,
                    updated_at=excluded.updated_at
                """,
                (run_id, connection_id, route_key, status, error_code, now),
            )

    def record_checkpoint(
        self,
        *,
        run_id: str,
        connection_id: str,
        route_key: str,
        source_id: str,
    ) -> None:
        """Persist completion using a one-way hash; raw source IDs are never checkpointed."""
        candidate_hash = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO collection_checkpoints(
                    run_id, connection_id, route_key, candidate_hash, completed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, connection_id, route_key, candidate_hash, _now()),
            )

    def link_document_to_run(self, *, run_id: str, document_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO collection_run_documents(run_id, document_id) "
                "VALUES (?, ?)",
                (run_id, document_id),
            )

    def finish_run(self, *, run_id: str, status: RunStatus) -> None:
        now = _now()
        completed_at = None if status is RunStatus.RUNNING else now
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE collection_runs SET status=?, updated_at=?, completed_at=? "
                "WHERE run_id=?",
                (status.value, now, completed_at, run_id),
            )

    def run_status(self, run_id: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM collection_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return str(row["status"]) if row else None

    def checkpoint_count(self, *, run_id: str, route_key: str | None = None) -> int:
        query = "SELECT COUNT(*) AS total FROM collection_checkpoints WHERE run_id=?"
        parameters: tuple[str, ...] = (run_id,)
        if route_key is not None:
            query += " AND route_key=?"
            parameters = (run_id, route_key)
        with self._lock, self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return int(row["total"])

    def has_hash(self, *, tenant_id: str, sink_id: str, sha256: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM documents WHERE tenant_id=? AND sink_id=? AND sha256=? LIMIT 1",
                (tenant_id, sink_id, sha256),
            ).fetchone()
            return row is not None

    def find_by_hash(
        self, *, tenant_id: str, sink_id: str, sha256: str
    ) -> Path | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT relative_path FROM documents "
                "WHERE tenant_id=? AND sink_id=? AND sha256=? LIMIT 1",
                (tenant_id, sink_id, sha256),
            ).fetchone()
        return Path(str(row["relative_path"])) if row else None

    def list_provenance(
        self, *, tenant_id: str, sink_id: str, sha256: str
    ) -> tuple[DocumentProvenance, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.connection_id, p.provider_id, p.route_key,
                       p.source_id_hash, p.external_id_hash
                FROM document_provenance AS p
                JOIN documents AS d ON d.document_id=p.document_id
                WHERE d.tenant_id=? AND d.sink_id=? AND d.sha256=?
                ORDER BY p.provider_id, p.route_key, p.connection_id
                """,
                (tenant_id, sink_id, sha256),
            ).fetchall()
        return tuple(
            DocumentProvenance(
                connection_id=str(row["connection_id"]),
                provider_id=str(row["provider_id"]),
                route_key=str(row["route_key"]),
                source_id_hash=str(row["source_id_hash"]),
                external_id_hash=(
                    str(row["external_id_hash"]) if row["external_id_hash"] else None
                ),
            )
            for row in rows
        )

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
            if row is not None:
                return str(row["sha256"]), str(row["outcome"])
            external_hash = hashlib.sha256(external_id.encode("utf-8")).hexdigest()
            row = connection.execute(
                """
                SELECT d.sha256, d.outcome
                FROM document_provenance AS p
                JOIN documents AS d ON d.document_id=p.document_id
                WHERE p.connection_id=? AND p.route_key=? AND p.external_id_hash=? LIMIT 1
                """,
                (connection_id, route_key, external_hash),
            ).fetchone()
            return (str(row["sha256"]), str(row["outcome"])) if row else None

    def record_document(
        self,
        *,
        document: ValidatedDocument,
        sink_id: str,
        receipt: SinkReceipt,
    ) -> str:
        candidate = document.candidate
        source_fingerprint = hashlib.sha256(candidate.source_id.encode("utf-8")).hexdigest()
        document_id = (
            f"{candidate.connection.connection_id}:{source_fingerprint}:{document.sha256}"
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO documents(
                    document_id, tenant_id, connection_id, provider_id, route_key,
                    external_id, sha256, sink_id, relative_path, outcome, sync_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
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
            row = connection.execute(
                "SELECT document_id FROM documents WHERE tenant_id=? AND sink_id=? AND sha256=?",
                (
                    candidate.connection.tenant_id.value,
                    sink_id,
                    document.sha256,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("journal document insert could not be resolved")
            resolved_id = str(row["document_id"])
            external_id_hash = (
                hashlib.sha256(candidate.external_id.encode("utf-8")).hexdigest()
                if candidate.external_id
                else None
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO document_provenance(
                    document_id, connection_id, provider_id, route_key,
                    source_id_hash, external_id_hash, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    str(candidate.connection.connection_id),
                    candidate.connection.provider_id,
                    candidate.route_key,
                    source_fingerprint,
                    external_id_hash,
                    document.validated_at.isoformat(),
                ),
            )
            return resolved_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
