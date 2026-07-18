"""Persistent monthly UVA/ZM calculation snapshots."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_tax_snapshot_store_path() -> Path:
    override = str(os.getenv("XW_STUDIO_TAX_SNAPSHOT_PATH") or "").strip()
    if override:
        path = Path(os.path.expandvars(os.path.expanduser(override)))
        if path.is_absolute():
            return path
        return (_repo_root() / path).resolve()
    return _repo_root() / "state" / "xw_studio_cache.sqlite"


def stable_payload_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TaxMonthlySnapshot:
    year: int
    month: int
    payload: dict[str, Any]
    payload_hash: str
    created_at: float
    age_seconds: float


class TaxMonthlySnapshotStore:
    """SQLite store for completed monthly tax calculations."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else default_tax_snapshot_store_path()
        self._lock = Lock()
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    def get_snapshot(self, year: int, month: int) -> TaxMonthlySnapshot | None:
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    row = con.execute(
                        """
                        SELECT payload_json, payload_hash, created_at
                        FROM tax_monthly_snapshot
                        WHERE year = ? AND month = ?
                        """,
                        (int(year), int(month)),
                    ).fetchone()
            except sqlite3.Error as exc:
                logger.warning("Tax snapshot read failed: %s", exc)
                return None
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        created_at = float(row["created_at"] or 0.0)
        payload_hash = str(row["payload_hash"] or "").strip() or stable_payload_hash(payload)
        return TaxMonthlySnapshot(
            year=int(year),
            month=int(month),
            payload=payload,
            payload_hash=payload_hash,
            created_at=created_at,
            age_seconds=max(0.0, time.time() - created_at),
        )

    def put_snapshot(self, year: int, month: int, payload: dict[str, Any]) -> TaxMonthlySnapshot | None:
        if not isinstance(payload, dict) or not payload:
            return None
        stored_payload = json.loads(json.dumps(payload, ensure_ascii=False))
        stored_payload.pop("cache", None)
        payload_hash = stable_payload_hash(stored_payload)
        now = time.time()
        payload_json = json.dumps(stored_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    con.execute(
                        """
                        INSERT INTO tax_monthly_snapshot (
                            year, month, payload_json, payload_hash, created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(year, month) DO UPDATE SET
                            payload_json = excluded.payload_json,
                            payload_hash = excluded.payload_hash,
                            created_at = excluded.created_at
                        """,
                        (int(year), int(month), payload_json, payload_hash, now),
                    )
            except sqlite3.Error as exc:
                logger.warning("Tax snapshot write failed: %s", exc)
                return None
        return TaxMonthlySnapshot(
            year=int(year),
            month=int(month),
            payload=stored_payload,
            payload_hash=payload_hash,
            created_at=now,
            age_seconds=0.0,
        )

    def clear_month(self, year: int, month: int) -> None:
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    con.execute(
                        "DELETE FROM tax_monthly_snapshot WHERE year = ? AND month = ?",
                        (int(year), int(month)),
                    )
            except sqlite3.Error as exc:
                logger.warning("Tax snapshot clear failed: %s", exc)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path)
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS tax_monthly_snapshot (
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (year, month)
                )
                """
            )
        self._initialized = True
