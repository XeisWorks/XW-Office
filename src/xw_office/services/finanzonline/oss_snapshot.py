"""Persistent EU-OSS quarter calculation snapshots."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from xw_office.services.finanzonline.monthly_snapshot import (
    default_tax_snapshot_store_path,
    stable_payload_hash,
)
from xw_office.services.finanzonline.oss_models import OssQuarterResult

logger = logging.getLogger(__name__)

OSS_SNAPSHOT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class OssQuarterSnapshot:
    year: int
    quarter: int
    result: OssQuarterResult
    payload_hash: str
    created_at: float
    age_seconds: float


class OssQuarterSnapshotStore:
    """SQLite store for completed EU-OSS quarter calculations."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else default_tax_snapshot_store_path()
        self._lock = Lock()
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    def get_snapshot(self, year: int, quarter: int) -> OssQuarterSnapshot | None:
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    row = con.execute(
                        """
                        SELECT payload_json, payload_hash, created_at
                        FROM oss_quarter_snapshot
                        WHERE year = ? AND quarter = ?
                        """,
                        (int(year), int(quarter)),
                    ).fetchone()
            except sqlite3.Error as exc:
                logger.warning("OSS snapshot read failed: %s", exc)
                return None
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or payload.get("schema_version") != OSS_SNAPSHOT_SCHEMA_VERSION:
            return None
        raw_result = payload.get("result")
        if not isinstance(raw_result, dict):
            return None
        try:
            result = OssQuarterResult.model_validate(raw_result)
        except Exception as exc:  # noqa: BLE001 - corrupt cache must not break live calculation.
            logger.warning("OSS snapshot payload invalid: %s", exc)
            return None
        created_at = float(row["created_at"] or 0.0)
        return OssQuarterSnapshot(
            year=int(year),
            quarter=int(quarter),
            result=result,
            payload_hash=str(row["payload_hash"] or "").strip() or stable_payload_hash(payload),
            created_at=created_at,
            age_seconds=max(0.0, time.time() - created_at),
        )

    def put_snapshot(self, result: OssQuarterResult) -> OssQuarterSnapshot | None:
        payload = {
            "schema_version": OSS_SNAPSHOT_SCHEMA_VERSION,
            "result": result.model_dump(mode="json", exclude={"cache"}),
        }
        payload_hash = stable_payload_hash(payload)
        now = time.time()
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    con.execute(
                        """
                        INSERT INTO oss_quarter_snapshot (
                            year, quarter, payload_json, payload_hash, created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(year, quarter) DO UPDATE SET
                            payload_json = excluded.payload_json,
                            payload_hash = excluded.payload_hash,
                            created_at = excluded.created_at
                        """,
                        (int(result.year), int(result.quarter), payload_json, payload_hash, now),
                    )
            except sqlite3.Error as exc:
                logger.warning("OSS snapshot write failed: %s", exc)
                return None
        return OssQuarterSnapshot(
            year=int(result.year),
            quarter=int(result.quarter),
            result=result,
            payload_hash=payload_hash,
            created_at=now,
            age_seconds=0.0,
        )

    def clear_quarter(self, year: int, quarter: int) -> None:
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    con.execute(
                        "DELETE FROM oss_quarter_snapshot WHERE year = ? AND quarter = ?",
                        (int(year), int(quarter)),
                    )
            except sqlite3.Error as exc:
                logger.warning("OSS snapshot clear failed: %s", exc)

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
                CREATE TABLE IF NOT EXISTS oss_quarter_snapshot (
                    year INTEGER NOT NULL,
                    quarter INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (year, quarter)
                )
                """
            )
        self._initialized = True
