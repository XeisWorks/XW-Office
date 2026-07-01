"""Local persistent cache for Wix order snapshots."""
from __future__ import annotations

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

# Invoice analysis only uses immutable order snapshot data (items, buyer and
# shipping address).  Positive snapshots and missing-order markers therefore
# stay valid until an explicit cache clear/prune.
DEFAULT_ORDER_TTL_SECONDS: float | None = None
DEFAULT_MISSING_TTL_SECONDS: float | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_wix_order_cache_path() -> Path:
    override = str(os.getenv("XW_STUDIO_WIX_ORDER_CACHE_PATH") or "").strip()
    if override:
        path = Path(os.path.expandvars(os.path.expanduser(override)))
        if path.is_absolute():
            return path
        return (_repo_root() / path).resolve()
    return _repo_root() / "state" / "xw_studio_cache.sqlite"


@dataclass(frozen=True)
class CachedWixOrder:
    found: bool
    order: dict[str, Any]
    age_seconds: float


class WixOrderCache:
    """SQLite-backed read-through cache for immutable Wix order snapshots."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else default_wix_order_cache_path()
        self._lock = Lock()
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    def get_order(
        self,
        *,
        site_id: str,
        account_id: str,
        reference: str,
        max_age_seconds: float | None = DEFAULT_ORDER_TTL_SECONDS,
        missing_ttl_seconds: float | None = DEFAULT_MISSING_TTL_SECONDS,
    ) -> CachedWixOrder | None:
        ref = str(reference or "").strip()
        if not ref:
            return None
        site = str(site_id or "").strip()
        account = str(account_id or "").strip()
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    row = con.execute(
                        """
                        SELECT found, order_json, fetched_at
                        FROM wix_order_cache
                        WHERE site_id = ? AND account_id = ? AND reference = ?
                        """,
                        (site, account, ref),
                    ).fetchone()
            except sqlite3.Error as exc:
                logger.warning("Wix order cache read failed: %s", exc)
                return None
        if row is None:
            return None
        found = bool(row["found"])
        fetched_at = float(row["fetched_at"] or 0.0)
        age = max(0.0, time.time() - fetched_at)
        ttl = max_age_seconds if found else missing_ttl_seconds
        if ttl is not None and age > ttl:
            return None
        if not found:
            return CachedWixOrder(found=False, order={}, age_seconds=age)
        try:
            payload = json.loads(str(row["order_json"] or "{}"))
        except json.JSONDecodeError:
            return None
        order = payload if isinstance(payload, dict) else {}
        return CachedWixOrder(found=True, order=order, age_seconds=age)

    def put_order(
        self,
        *,
        site_id: str,
        account_id: str,
        reference: str,
        order: dict[str, Any],
    ) -> None:
        if not isinstance(order, dict) or not order:
            return
        references = self._order_references(reference, order)
        if not references:
            return
        site = str(site_id or "").strip()
        account = str(account_id or "").strip()
        payload = json.dumps(order, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        order_id = str(order.get("id") or "").strip()
        order_number = str(order.get("number") or order.get("orderNumber") or "").strip()
        updated_at = str(
            order.get("updatedDate")
            or order.get("updatedAt")
            or order.get("dateUpdated")
            or ""
        ).strip()
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    con.executemany(
                        """
                        INSERT INTO wix_order_cache (
                            site_id, account_id, reference, wix_order_id, order_number,
                            found, order_json, fetched_at, order_updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                        ON CONFLICT(site_id, account_id, reference) DO UPDATE SET
                            wix_order_id = excluded.wix_order_id,
                            order_number = excluded.order_number,
                            found = 1,
                            order_json = excluded.order_json,
                            fetched_at = excluded.fetched_at,
                            order_updated_at = excluded.order_updated_at
                        """,
                        [
                            (site, account, ref, order_id, order_number, payload, now, updated_at)
                            for ref in references
                        ],
                    )
            except sqlite3.Error as exc:
                logger.warning("Wix order cache write failed: %s", exc)

    def put_missing(self, *, site_id: str, account_id: str, reference: str) -> None:
        ref = str(reference or "").strip()
        if not ref:
            return
        site = str(site_id or "").strip()
        account = str(account_id or "").strip()
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    con.execute(
                        """
                        INSERT INTO wix_order_cache (
                            site_id, account_id, reference, found, order_json, fetched_at
                        )
                        VALUES (?, ?, ?, 0, '{}', ?)
                        ON CONFLICT(site_id, account_id, reference) DO UPDATE SET
                            found = 0,
                            order_json = '{}',
                            fetched_at = excluded.fetched_at,
                            wix_order_id = '',
                            order_number = '',
                            order_updated_at = ''
                        """,
                        (site, account, ref, time.time()),
                    )
            except sqlite3.Error as exc:
                logger.warning("Wix order cache missing-write failed: %s", exc)

    def clear(self) -> None:
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    con.execute("DELETE FROM wix_order_cache")
            except sqlite3.Error as exc:
                logger.warning("Wix order cache clear failed: %s", exc)

    def prune_older_than(self, max_age_seconds: float) -> int:
        cutoff = time.time() - max(0.0, max_age_seconds)
        with self._lock:
            try:
                self._ensure_schema()
                with self._connect() as con:
                    cur = con.execute(
                        "DELETE FROM wix_order_cache WHERE fetched_at < ?",
                        (cutoff,),
                    )
                    return int(cur.rowcount or 0)
            except sqlite3.Error as exc:
                logger.warning("Wix order cache prune failed: %s", exc)
                return 0

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
                CREATE TABLE IF NOT EXISTS wix_order_cache (
                    site_id TEXT NOT NULL,
                    account_id TEXT NOT NULL DEFAULT '',
                    reference TEXT NOT NULL,
                    wix_order_id TEXT NOT NULL DEFAULT '',
                    order_number TEXT NOT NULL DEFAULT '',
                    found INTEGER NOT NULL DEFAULT 1,
                    order_json TEXT NOT NULL DEFAULT '{}',
                    fetched_at REAL NOT NULL,
                    order_updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (site_id, account_id, reference)
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS ix_wix_order_cache_order_id "
                "ON wix_order_cache(site_id, account_id, wix_order_id)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS ix_wix_order_cache_order_number "
                "ON wix_order_cache(site_id, account_id, order_number)"
            )
        self._initialized = True

    @staticmethod
    def _order_references(reference: str, order: dict[str, Any]) -> list[str]:
        refs = [
            str(reference or "").strip(),
            str(order.get("id") or "").strip(),
            str(order.get("number") or "").strip(),
            str(order.get("orderNumber") or "").strip(),
        ]
        return list(dict.fromkeys(ref for ref in refs if ref))
