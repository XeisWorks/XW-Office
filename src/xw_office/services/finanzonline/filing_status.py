"""Persistent filing acknowledgements, separate from replaceable tax snapshots."""
from __future__ import annotations

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

logger = logging.getLogger(__name__)

_UVA_KENNZAHLEN: tuple[tuple[str, str, str], ...] = (
    ("KZ000", "A000", "KZ000"),
    ("KZ011", "A011", "KZ011"),
    ("KZ017", "A017", "KZ017"),
    ("KZ021", "A021", "KZ021"),
    ("KZ022", "A022", "KZ022"),
    ("KZ029", "A029", "KZ029"),
    ("KZ006", "A006", "KZ006"),
    ("KZ057", "A057", "KZ057"),
    ("KZ070", "B070", "KZ070"),
    ("KZ072", "B072", "KZ072"),
    ("KZ060", "C060", "KZ060"),
    ("KZ065", "C065", "KZ065"),
    ("KZ066", "C066", "KZ066"),
    ("KZ090", "D090", "KZ090"),
)


def uva_submission_kennzahlen(values: dict[str, object]) -> dict[str, object]:
    """Return the exact U30 keys from either a calculation or submission payload."""
    return {
        target: values.get(submission_key) or values.get(calculation_key) or "0.00"
        for target, calculation_key, submission_key in _UVA_KENNZAHLEN
    }


def uva_calculation_hash(payload: dict[str, object]) -> str:
    values = payload.get("kennzahlen")
    if not isinstance(values, dict):
        raise ValueError("UVA calculation has no kennzahlen mapping.")
    year = payload.get("jahr")
    month = payload.get("monat")
    if not isinstance(year, int) or not isinstance(month, int):
        raise ValueError("UVA calculation has no valid year/month.")
    return stable_payload_hash(
        {
            "year": year,
            "month": month,
            "kennzahlen": uva_submission_kennzahlen(values),
            "zahlbetrag": str(payload.get("zahlbetrag") or "0.00"),
            "rule_version": str(payload.get("rule_version") or ""),
        }
    )


def oss_calculation_hash(payload: dict[str, object]) -> str:
    """Hash only financial OSS output; volatile cache diagnostics are excluded."""
    normalized = dict(payload)
    normalized.pop("cache", None)
    return stable_payload_hash(normalized)


@dataclass(frozen=True)
class FilingStatus:
    filing_type: str
    year: int
    period: int
    calculation_hash: str
    confirmed_at: float
    confirmation_source: str
    reference: str


class FilingStatusStore:
    """Keep confirmed submissions keyed to the exact calculation that was filed."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else default_tax_snapshot_store_path()
        self._lock = Lock()
        self._initialized = False

    def get_status(
        self, filing_type: str, year: int, period: int, calculation_hash: str
    ) -> FilingStatus | None:
        self._validate_key(filing_type, year, period, calculation_hash)
        with self._lock:
            self._ensure_schema()
            with self._connect() as con:
                row = con.execute(
                    """
                    SELECT confirmed_at, confirmation_source, reference
                    FROM tax_filing_status
                    WHERE filing_type = ? AND year = ? AND period = ? AND calculation_hash = ?
                    """,
                    (filing_type, int(year), int(period), calculation_hash),
                ).fetchone()
        if row is None:
            return None
        return FilingStatus(
            filing_type=filing_type,
            year=int(year),
            period=int(period),
            calculation_hash=calculation_hash,
            confirmed_at=float(row["confirmed_at"]),
            confirmation_source=str(row["confirmation_source"]),
            reference=str(row["reference"] or ""),
        )

    def record_submission(
        self,
        filing_type: str,
        year: int,
        period: int,
        calculation_hash: str,
        *,
        confirmation_source: str,
        reference: str = "",
    ) -> FilingStatus:
        self._validate_key(filing_type, year, period, calculation_hash)
        if not confirmation_source.strip():
            raise ValueError("A filing confirmation source is required.")
        confirmed_at = time.time()
        with self._lock:
            self._ensure_schema()
            with self._connect() as con:
                con.execute(
                    """
                    INSERT INTO tax_filing_status (
                        filing_type, year, period, calculation_hash, confirmed_at,
                        confirmation_source, reference
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(filing_type, year, period, calculation_hash) DO UPDATE SET
                        confirmed_at = excluded.confirmed_at,
                        confirmation_source = excluded.confirmation_source,
                        reference = excluded.reference
                    """,
                    (
                        filing_type, int(year), int(period), calculation_hash, confirmed_at,
                        confirmation_source.strip(), reference.strip(),
                    ),
                )
        logger.info(
            "Recorded %s filing confirmation for %04d period=%d hash=%s",
            filing_type, year, period, calculation_hash[:12],
        )
        return FilingStatus(
            filing_type=filing_type,
            year=int(year),
            period=int(period),
            calculation_hash=calculation_hash,
            confirmed_at=confirmed_at,
            confirmation_source=confirmation_source.strip(),
            reference=reference.strip(),
        )

    def _validate_key(self, filing_type: str, year: int, period: int, calculation_hash: str) -> None:
        if filing_type not in {"uva", "oss"}:
            raise ValueError(f"Unsupported filing type: {filing_type}")
        if year < 2000 or not 1 <= period <= (12 if filing_type == "uva" else 4):
            raise ValueError("Invalid filing period.")
        if len(calculation_hash) != 64 or any(char not in "0123456789abcdef" for char in calculation_hash):
            raise ValueError("Calculation hash must be a lowercase SHA-256 digest.")

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
                CREATE TABLE IF NOT EXISTS tax_filing_status (
                    filing_type TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    period INTEGER NOT NULL,
                    calculation_hash TEXT NOT NULL,
                    confirmed_at REAL NOT NULL,
                    confirmation_source TEXT NOT NULL,
                    reference TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (filing_type, year, period, calculation_hash)
                )
                """
            )
        self._initialized = True
