"""The small Flow facade must stop on incomplete analysis before any sevDesk write."""
from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.clearing.models import (
    BookingBatchResult, BookingItemResult, ClearingAnalysis, ClearingCandidate,
    MatchStatus, TransactionKind,
)
from xw_office.web.routers.payment_clearing import ClearingRunCoordinator, build_clearing_router

VIENNA = ZoneInfo("Europe/Vienna")


class FakeService:
    def __init__(self, *, warnings: tuple[str, ...] = ()) -> None:
        self.warnings = warnings
        self.book_calls = 0

    def analyze(self, start: date, end: date, *, progress):
        progress(100, "Analyse abgeschlossen")
        row = ClearingCandidate(
            candidate_id="sample", provider="stripe", kind=TransactionKind.PAYMENT,
            provider_ref="ch_sample", order_number="12345", invoice_id=1,
            invoice_number="RE-1", customer="", amount=Decimal("10.00"),
            payment_date=datetime(2026, 11, 17, tzinfo=VIENNA), status=MatchStatus.READY,
            reason="", selected=True, account_id=1,
        )
        return ClearingAnalysis(
            started_at=datetime.now(VIENNA),
            start_date=datetime.combine(start, datetime.min.time(), tzinfo=VIENNA),
            end_date=datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=VIENNA),
            candidates=(
                row,
                replace(
                    row, candidate_id="refund", provider_ref="re_sample",
                    kind=TransactionKind.REFUND, status=MatchStatus.REFUND_IMPORT, selected=False,
                ),
                replace(
                    row, candidate_id="old", provider_ref="ch_old",
                    status=MatchStatus.ALREADY_BOOKED, selected=False,
                ),
            ),
            warnings=self.warnings,
        )

    def book_selected(self, rows, *, progress):
        self.book_calls += 1
        progress(100, "done")
        return BookingBatchResult((BookingItemResult(rows[0].candidate_id, True, MatchStatus.BOOKED, "done"),))


@pytest.fixture()
def setup():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    SettingKV.__table__.create(engine)
    repo = SettingKvRepository(sessionmaker(bind=engine))
    try:
        yield repo
    finally:
        engine.dispose()


def _wait(coordinator: ClearingRunCoordinator, run_id: str):
    for _ in range(100):
        result = coordinator.get(run_id)
        if result and result["state"] != "running":
            return result
        time.sleep(0.01)
    pytest.fail("Clearing job did not finish")


def test_provider_warning_stops_before_booking(setup):
    service = FakeService(warnings=("Stripe HTTP 401",))
    coordinator = ClearingRunCoordinator(setup, lambda: service, today=lambda: date(2026, 11, 17))
    started = coordinator.start("2026-11", "first")
    result = _wait(coordinator, str(started["run_id"]))
    assert result["state"] == "error"
    assert result["warnings"] == 1
    assert service.book_calls == 0


def test_success_is_idempotent_for_same_request_key(setup):
    service = FakeService()
    coordinator = ClearingRunCoordinator(setup, lambda: service, today=lambda: date(2026, 11, 17))
    started = coordinator.start("2026-11", "same-key")
    result = _wait(coordinator, str(started["run_id"]))
    assert result["state"] == "complete"
    assert result["booked"] == 1
    assert result["manual"] == 1
    assert result["already_booked"] == 1
    again = coordinator.start("2026-11", "same-key")
    assert again["run_id"] == started["run_id"]
    assert service.book_calls == 1


def test_web_route_requires_machine_secret(setup):
    coordinator = ClearingRunCoordinator(setup, FakeService, today=lambda: date(2026, 11, 17))
    app = FastAPI()
    app.include_router(build_clearing_router(
        coordinator, secret="synthetic-test-secret", read_enabled=True, write_enabled=True,
    ))
    with TestClient(app) as client:
        assert client.post("/api/v1/clearing/runs", json={"month": "2026-11"}).status_code == 401
        response = client.post(
            "/api/v1/clearing/runs", json={"month": "2026-11"},
            headers={"X-XW-Flow-Secret": "synthetic-test-secret", "Idempotency-Key": "route"},
        )
        assert response.status_code == 202
        result = client.get(
            f"/api/v1/clearing/runs/{response.json()['run_id']}",
            headers={"X-XW-Flow-Secret": "synthetic-test-secret"},
        )
        assert result.status_code == 200
