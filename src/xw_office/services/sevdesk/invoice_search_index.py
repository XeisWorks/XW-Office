"""Shared, persistent search index over sevDesk invoices.

The index is filled from every invoice page that is listed from sevDesk (UI loads,
live searches and a background sync), so a search normally never has to walk the
paginated sevDesk history. Search results are re-validated against sevDesk for stale
rows before they are returned.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime

import httpx
from sqlalchemy.exc import SQLAlchemyError

from xw_office.core.exceptions import SevdeskApiError
from xw_office.repositories.invoice_search_index import (
    InvoiceIndexRow,
    InvoiceSearchIndexRepository,
)
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.sevdesk.invoice_client import (
    InvoiceClient,
    InvoiceSummary,
    normalize_search_text,
)

logger = logging.getLogger(__name__)

_STATE_KEY = "rechnungen.invoice_search_index_state_v1"
_PAGE_SIZE = 200
# Consecutive pages overlap so invoices created/deleted while paging cannot slip through.
_PAGE_OVERLAP = 10
_SYNC_WAVE_PAGES = 4
_MAX_SYNC_PAGES = 5000
_FULL_SYNC_MAX_AGE_SECONDS = 7 * 24 * 3600.0
_RECENT_SYNC_MIN_INTERVAL_SECONDS = 60.0
_RECENT_SYNC_PAGES_SEARCH = 1
_RECENT_SYNC_PAGES_BACKGROUND = 3
_STALE_HIT_SECONDS = 300.0
_MAX_REFRESH_DAYS = 6
_MAX_HITS = 500
_DEFAULT_SEARCHED_DAYS = 100

_REMOTE_ERRORS = (SevdeskApiError, httpx.HTTPError)


@dataclass(frozen=True)
class _IndexState:
    complete: bool = False
    full_sync_at: float = 0.0


@dataclass(frozen=True)
class _Hit:
    summary: InvoiceSummary
    synced_at: float


class InvoiceSearchIndexService:
    """Keeps the invoice index current and answers searches from it."""

    def __init__(
        self,
        client: InvoiceClient,
        repository: InvoiceSearchIndexRepository,
        settings_repo: SettingKvRepository | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._repo = repository
        self._settings = settings_repo
        self._clock = clock
        self._memory_state = _IndexState()
        self._last_recent_sync = 0.0
        self._sync_lock = threading.Lock()
        client.add_summary_observer(self.index_summaries)

    # ------------------------------------------------------------------ writing

    def index_summaries(self, summaries: list[InvoiceSummary]) -> None:
        """Upsert freshly listed invoices (called for every sevDesk list response)."""
        now = self._clock()
        rows = [self._to_row(summary, now) for summary in summaries if summary.id]
        if not rows:
            return
        try:
            self._repo.upsert_many(rows)
        except SQLAlchemyError as exc:
            logger.warning("Invoice search index upsert failed: %s", exc)

    def forget(self, invoice_id: str) -> None:
        try:
            self._repo.delete(str(invoice_id))
        except SQLAlchemyError as exc:
            logger.warning("Invoice search index delete failed: %s", exc)

    @staticmethod
    def _to_row(summary: InvoiceSummary, now: float) -> InvoiceIndexRow:
        parts = [
            normalize_search_text(summary.invoice_number),
            normalize_search_text(summary.contact_name),
            normalize_search_text(summary.order_reference),
            normalize_search_text(summary.sevdesk_reference),
        ]
        return InvoiceIndexRow(
            invoice_id=summary.id,
            invoice_number=summary.invoice_number,
            invoice_date=summary.invoice_date,
            status_code=summary.status_code,
            search_text=" ".join(part for part in parts if part),
            payload_json=json.dumps(summary.model_dump(by_alias=True), ensure_ascii=False),
            synced_at=now,
        )

    # -------------------------------------------------------------------- state

    def _load_state(self) -> _IndexState:
        if self._settings is None:
            return self._memory_state
        raw = self._settings.get_value_json(_STATE_KEY)
        if not raw:
            return _IndexState()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return _IndexState()
        if not isinstance(payload, dict):
            return _IndexState()
        try:
            return _IndexState(
                complete=bool(payload.get("complete")),
                full_sync_at=float(payload.get("full_sync_at") or 0.0),
            )
        except (TypeError, ValueError):
            return _IndexState()

    def _save_state(self, state: _IndexState) -> None:
        self._memory_state = state
        if self._settings is None:
            return
        self._settings.set_value_json(
            _STATE_KEY,
            json.dumps({"complete": state.complete, "full_sync_at": state.full_sync_at}),
        )

    def is_complete(self) -> bool:
        try:
            return self._load_state().complete
        except SQLAlchemyError as exc:
            logger.warning("Invoice search index state unavailable: %s", exc)
            return False

    # --------------------------------------------------------------------- sync

    def sync(
        self,
        *,
        force_full: bool = False,
        should_abort: Callable[[], bool] | None = None,
    ) -> str:
        """Bring the index up to date; returns ``full``, ``recent``, ``busy`` or ``aborted``."""
        if not self._sync_lock.acquire(blocking=False):
            return "busy"
        try:
            state = self._load_state()
            age = self._clock() - state.full_sync_at
            if state.complete and not force_full and age < _FULL_SYNC_MAX_AGE_SECONDS:
                self.refresh_recent(pages=_RECENT_SYNC_PAGES_BACKGROUND, force=True)
                return "recent"
            return self._full_sync(should_abort)
        finally:
            self._sync_lock.release()

    def _full_sync(self, should_abort: Callable[[], bool] | None) -> str:
        step = _PAGE_SIZE - _PAGE_OVERLAP
        offset = 0
        total_pages = 0
        finished = False
        while not finished:
            if should_abort is not None and should_abort():
                return "aborted"
            if total_pages >= _MAX_SYNC_PAGES:
                raise RuntimeError("Invoice index sync exceeded the page limit")
            offsets = [offset + index * step for index in range(_SYNC_WAVE_PAGES)]
            pages = self._client.fetch_pages_parallel(offsets, limit=_PAGE_SIZE, status=None)
            total_pages += len(pages)
            for page in pages:
                if len(page) < _PAGE_SIZE:
                    finished = True
                    break
            offset += step * _SYNC_WAVE_PAGES
        self._save_state(_IndexState(complete=True, full_sync_at=self._clock()))
        self._last_recent_sync = self._clock()
        logger.info("Invoice search index full sync finished (%s pages)", total_pages)
        return "full"

    def refresh_recent(self, *, pages: int = _RECENT_SYNC_PAGES_SEARCH, force: bool = False) -> None:
        """Re-list the newest invoices so new invoices and status changes are indexed."""
        now = self._clock()
        if not force and (now - self._last_recent_sync) < _RECENT_SYNC_MIN_INTERVAL_SECONDS:
            return
        step = _PAGE_SIZE - _PAGE_OVERLAP
        offsets = [index * step for index in range(max(1, pages))]
        try:
            self._client.fetch_pages_parallel(offsets, limit=_PAGE_SIZE, status=None)
        except _REMOTE_ERRORS as exc:
            logger.warning("Invoice search index refresh failed: %s", exc)
            return
        self._last_recent_sync = now

    # ------------------------------------------------------------------- search

    def search(self, query: str) -> tuple[list[InvoiceSummary], int] | None:
        """Search the index; ``None`` means the caller must fall back to the live search."""
        needle = normalize_search_text(query)
        if not needle:
            return None
        try:
            if not self._load_state().complete:
                return None
            self.refresh_recent()
            hits = self._query(needle)
            if hits:
                if self._refresh_stale(hits):
                    hits = self._query(needle)
            else:
                try:
                    found = self._client.search_by_invoice_number(query)
                except _REMOTE_ERRORS as exc:
                    logger.warning("Invoice number lookup failed: %s", exc)
                    found = []
                if found:
                    hits = self._query(needle)
            return [hit.summary for hit in hits], self._searched_days()
        except SQLAlchemyError as exc:
            logger.warning("Invoice search index unavailable, using live search: %s", exc)
            return None

    def _query(self, needle: str) -> list[_Hit]:
        hits: list[_Hit] = []
        for row in self._repo.search(needle.split(), limit=_MAX_HITS):
            try:
                summary = InvoiceSummary.model_validate(json.loads(row.payload_json))
            except (ValueError, TypeError):
                continue
            if InvoiceClient._matches_search_query(summary, needle):
                hits.append(_Hit(summary=summary, synced_at=row.synced_at))
        return hits

    def _searched_days(self) -> int:
        oldest = InvoiceClient._parse_invoice_date(self._repo.oldest_invoice_date())
        if oldest is None:
            return _DEFAULT_SEARCHED_DAYS
        return max(1, (date.today() - oldest).days)

    def _refresh_stale(self, hits: list[_Hit]) -> bool:
        """Re-list the invoice days of stale hits; drop rows sevDesk no longer returns."""
        cutoff = self._clock() - _STALE_HIT_SECONDS
        by_day: dict[date, set[str]] = {}
        for hit in hits:
            if hit.synced_at >= cutoff:
                continue
            day = InvoiceClient._parse_invoice_date(hit.summary.invoice_date)
            if day is not None:
                by_day.setdefault(day, set()).add(hit.summary.id)
        days = sorted(by_day, reverse=True)[:_MAX_REFRESH_DAYS]
        if not days:
            return False
        with ThreadPoolExecutor(max_workers=min(len(days), 4)) as pool:
            list(pool.map(lambda day: self._refresh_day(day, by_day[day]), days))
        return True

    def _refresh_day(self, day: date, invoice_ids: set[str]) -> None:
        start = datetime.combine(day - timedelta(days=1), dtime.min)
        end = datetime.combine(day + timedelta(days=1), dtime.max)
        try:
            page = self._client.list_invoice_summaries(
                limit=_PAGE_SIZE,
                offset=0,
                start_timestamp=int(start.timestamp()),
                end_timestamp=int(end.timestamp()),
            )
        except _REMOTE_ERRORS as exc:
            logger.warning("Invoice refresh for %s failed: %s", day, exc)
            return
        if not page or len(page) >= _PAGE_SIZE:
            return
        lower, upper = day - timedelta(days=2), day + timedelta(days=2)
        for summary in page:
            parsed = InvoiceClient._parse_invoice_date(summary.invoice_date)
            if parsed is None or not (lower <= parsed <= upper):
                # The date filter was ignored or unreliable: never conclude deletions.
                return
        returned = {summary.id for summary in page}
        for missing_id in invoice_ids - returned:
            logger.info("Removing invoice %s from search index (gone in sevDesk)", missing_id)
            self.forget(missing_id)
