"""Tests for the shared sevDesk invoice search index and parallel invoice search."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models import Base
from xw_office.repositories.invoice_search_index import InvoiceSearchIndexRepository
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.sevdesk.invoice_client import InvoiceClient, normalize_search_text
from xw_office.services.sevdesk.invoice_search_index import InvoiceSearchIndexService


class _Response:
    def __init__(self, objects: list[dict[str, Any]]) -> None:
        self._objects = objects

    def json(self) -> dict[str, Any]:
        return {"objects": self._objects}


class _FakeConnection:
    """Serves invoices newest-first with limit/offset and optional date/number filters."""

    def __init__(self, invoices: list[dict[str, Any]], *, honor_filters: bool = True) -> None:
        self.invoices = invoices
        self.honor_filters = honor_filters
        self.calls: list[dict[str, Any]] = []

    def get(self, path: str, **kwargs: Any) -> _Response:
        assert path == "/Invoice"
        params = dict(kwargs.get("params", {}))
        self.calls.append(params)
        rows = sorted(self.invoices, key=lambda item: int(item["id"]), reverse=True)
        if self.honor_filters:
            number = params.get("invoiceNumber")
            if number:
                rows = [row for row in rows if row["invoiceNumber"] == number]
            if "startDate" in params or "endDate" in params:
                lo = int(params.get("startDate", 0))
                hi = int(params.get("endDate", 10**12))
                rows = [
                    row for row in rows
                    if lo <= _ts(row["invoiceDate"]) <= hi
                ]
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 100))
        return _Response(rows[offset : offset + limit])


def _ts(iso: str) -> int:
    from datetime import datetime

    return int(datetime.fromisoformat(iso).replace(tzinfo=None).timestamp())


def _invoice(index: int, *, days_ago: int, name: str = "Kunde", status: str = "200") -> dict[str, Any]:
    day = date.today() - timedelta(days=days_ago)
    return {
        "id": str(index),
        "invoiceNumber": f"RE-{index}",
        "invoiceDate": f"{day.isoformat()}T00:00:00+01:00",
        "status": status,
        "contact": {"name": name},
        "reference": f"Bestellung {10000 + index}",
    }


def _build(invoices: list[dict[str, Any]], *, honor_filters: bool = True):
    connection = _FakeConnection(invoices, honor_filters=honor_filters)
    client = InvoiceClient(connection)  # type: ignore[arg-type]
    import os
    import tempfile

    handle, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(handle)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repo = InvoiceSearchIndexRepository(factory)
    clock = {"now": 1_000_000.0}
    service = InvoiceSearchIndexService(
        client, repo, SettingKvRepository(factory), clock=lambda: clock["now"]
    )
    return connection, client, repo, service, clock


def test_normalize_search_text_handles_umlauts() -> None:
    assert normalize_search_text("  Müller-Größe ") == "mueller groesse"


def test_search_falls_back_until_index_is_complete() -> None:
    _, _, _, service, _ = _build([_invoice(1, days_ago=5)])
    assert service.search("RE-1") is None


def test_full_sync_then_search_finds_old_invoice_without_walking_history() -> None:
    invoices = [_invoice(i, days_ago=i // 2, name="Alt" if i == 3 else "Neu") for i in range(1, 451)]
    connection, _, repo, service, clock = _build(invoices)

    assert service.sync() == "full"
    assert repo.count() == 450
    assert service.is_complete()

    connection.calls.clear()
    clock["now"] += 10
    result = service.search("alt")
    assert result is not None
    summaries, searched_days = result
    assert [s.id for s in summaries] == ["3"]
    assert searched_days >= 1
    # Only the throttled newest-page refresh may hit sevDesk, never the history.
    assert len(connection.calls) <= 1


def test_search_matches_normalized_tokens_across_fields() -> None:
    invoices = [_invoice(1, days_ago=1, name="Müller GmbH"), _invoice(2, days_ago=2, name="Maier")]
    _, _, _, service, _ = _build(invoices)
    service.sync()
    summaries, _ = service.search("mueller 10001") or ([], 0)
    assert [s.id for s in summaries] == ["1"]


def test_stale_hit_is_refreshed_and_status_updates() -> None:
    invoices = [_invoice(1, days_ago=30, status="100")]
    connection, _, _, service, clock = _build(invoices)
    service.sync()
    invoices[0]["status"] = "1000"
    clock["now"] += 3600

    summaries, _ = service.search("RE-1") or ([], 0)
    assert summaries[0].status_code == 1000


def test_stale_hit_deleted_in_sevdesk_is_removed() -> None:
    invoices = [_invoice(1, days_ago=30, name="Erster"), _invoice(2, days_ago=30, name="Zweiter")]
    connection, _, repo, service, clock = _build(invoices)
    service.sync()
    connection.invoices[:] = [invoices[1]]
    clock["now"] += 3600

    summaries, _ = service.search("erster") or ([], 0)
    assert summaries == []
    assert repo.count() == 1


def test_ignored_date_filter_never_deletes_rows() -> None:
    invoices = [_invoice(1, days_ago=300, name="Erster"), _invoice(2, days_ago=1, name="Zweiter")]
    connection, _, repo, service, clock = _build(invoices, honor_filters=False)
    service.sync()
    clock["now"] += 3600

    summaries, _ = service.search("erster") or ([], 0)
    assert [s.id for s in summaries] == ["1"]
    assert repo.count() == 2


def test_forget_removes_invoice() -> None:
    _, _, repo, service, _ = _build([_invoice(1, days_ago=1)])
    service.sync()
    service.forget("1")
    assert repo.count() == 0


def test_sync_is_incremental_after_full_sync() -> None:
    invoices = [_invoice(i, days_ago=1) for i in range(1, 6)]
    connection, _, repo, service, clock = _build(invoices)
    assert service.sync() == "full"
    invoices.append(_invoice(6, days_ago=0))
    clock["now"] += 600
    connection.calls.clear()
    assert service.sync() == "recent"
    assert repo.count() == 6
    assert len(connection.calls) <= 3


def test_index_payload_round_trips_summary() -> None:
    _, _, repo, service, _ = _build([_invoice(7, days_ago=2, name="Round Trip")])
    service.sync()
    row = repo.search(["round"])[0]
    assert json.loads(row.payload_json)["invoiceNumber"] == "RE-7"


def test_live_search_uses_parallel_pages_and_page_cache() -> None:
    invoices = [_invoice(i, days_ago=i, name="Ziel" if i == 450 else "x") for i in range(1, 451)]
    connection = _FakeConnection(invoices)
    client = InvoiceClient(connection)  # type: ignore[arg-type]

    summaries, _ = client.search_invoice_summaries("ziel", initial_window_days=100, window_step_days=400)
    assert [s.id for s in summaries] == ["450"]
    first_calls = len(connection.calls)

    connection.calls.clear()
    client.search_invoice_summaries("ziel", initial_window_days=100, window_step_days=400)
    # Page 0 is always re-fetched, older pages come from the cache.
    assert len(connection.calls) < first_calls
    assert connection.calls[0]["offset"] == 0


def test_search_by_invoice_number_verifies_results() -> None:
    connection = _FakeConnection([_invoice(1, days_ago=1), _invoice(2, days_ago=2)], honor_filters=False)
    client = InvoiceClient(connection)  # type: ignore[arg-type]
    assert [s.id for s in client.search_by_invoice_number("RE-2")] == ["2"]
    assert client.search_by_invoice_number("a b") == []


def test_observer_failure_does_not_break_listing() -> None:
    connection = _FakeConnection([_invoice(1, days_ago=1)])
    client = InvoiceClient(connection)  # type: ignore[arg-type]

    def broken(_: list[Any]) -> None:
        raise RuntimeError("boom")

    client.add_summary_observer(broken)
    assert len(client.list_invoice_summaries(limit=10)) == 1


@pytest.mark.parametrize("token", ["100%", "a_b"])
def test_like_wildcards_are_escaped(token: str) -> None:
    _, _, repo, service, _ = _build([_invoice(1, days_ago=1, name="Normal")])
    service.sync()
    assert repo.search([token]) == []
