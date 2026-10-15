from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tests.unit.test_expense_audit_service import _BankProviderStub, _bank_row
from xw_office.core.config import AppConfig
from xw_office.models.base import Base
from xw_office.repositories.expense_pipeline import ExpensePipelineRepository
from xw_office.services.expenses.bank_provider import BankDocumentLink, DocumentLinkScan
from xw_office.services.expenses.service import ExpenseAuditService
from xw_office.services.expenses.xw_flow_expense_client import FlowExpense, XwFlowExpenseClient
from xw_office.services.secrets.service import SecretService


@pytest.fixture
def pipeline() -> Generator[ExpensePipelineRepository, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield ExpensePipelineRepository(sessionmaker[Session](engine, expire_on_commit=False))
    engine.dispose()


def capture(
    expense_id: str, *, tenant: str = "xw", category: str = "wm",
    expense_date: str | None = "2026-09-04",
) -> FlowExpense:
    return XwFlowExpenseClient._parse({
        "id": expense_id, "tenant_key": tenant, "category_key": category,
        "expense_date": expense_date, "gross_amount": "23.10", "recipient": expense_id,
        "purpose": "WM-Ausgabe", "payment_source": "private_cash",
        "receipt_state": "attached", "attachment_ids": [f"{expense_id}-attachment"],
    })


def test_shared_bank_expenses_use_only_xw_wm_outgoing_cache_and_current_period(
    pipeline: ExpensePipelineRepository,
) -> None:
    xw_provider = _BankProviderStub(
        [
            _bank_row(external_id="wm"),
            _bank_row(external_id="xw"),
            _bank_row(external_id="uncategorized"),
            replace(_bank_row(external_id="incoming"), amount=Decimal("23.10"), direction="incoming"),
            replace(_bank_row(external_id="old"), value_date=date(2026, 8, 31)),
        ],
        DocumentLinkScan((
            BankDocumentLink("wm", "Voucher", "V-WM", "WM-Beleg"),
        ), True),
    )
    wuedara_provider = _BankProviderStub([_bank_row(external_id="wm")], account_id="WUEDARA")
    service = ExpenseAuditService(
        pipeline_repo=pipeline,
        tenant_providers={"xw": xw_provider, "wuedara": wuedara_provider},  # type: ignore[dict-item]
    )
    start, end = date(2026, 8, 1), date(2026, 9, 30)
    service.list_bank_expenses(start=start, end=end, outgoing_only=False)
    snapshots = {
        row.external_id: row for row in pipeline.list_snapshots(start=start, end=end, direction="")
    }
    for external_id, category in (("wm", "wm"), ("xw", "xw"), ("incoming", "wm"), ("old", "wm")):
        service.assign_transaction_position(transaction_id=str(snapshots[external_id].id), position_key=category)
    wuedara = service.for_tenant("wuedara")
    wuedara_rows = wuedara.list_bank_expenses(start=start, end=end)
    wuedara.assign_transaction_position(transaction_id=wuedara_rows[0].transaction_id, position_key="wm")
    before = len(pipeline.list_snapshots(start=start, end=end, direction=""))
    calls_before = (xw_provider.fetch_calls, xw_provider.resolve_calls, wuedara_provider.fetch_calls)

    shared = wuedara.list_wuedara_shared_bank_expenses(
        start=date(2026, 9, 1), end=date(2026, 9, 30)
    )
    assert [row.transaction_id for row in shared] == [str(snapshots["wm"].id)]
    assert shared[0].documents[0].document_number == "WM-Beleg"
    assert shared[0].documents[0].url.endswith("/ex/detail/id/V-WM")
    assert (xw_provider.fetch_calls, xw_provider.resolve_calls, wuedara_provider.fetch_calls) == calls_before
    assert len(pipeline.list_snapshots(start=start, end=end, direction="")) == before

    service.assign_transaction_position(transaction_id=str(snapshots["wm"].id), position_key="mh")
    assert not wuedara.list_wuedara_shared_bank_expenses(
        start=date(2026, 9, 1), end=date(2026, 9, 30)
    )
    service.assign_transaction_position(
        transaction_id=str(snapshots["uncategorized"].id), position_key="wm"
    )
    assert [
        row.transaction_id for row in wuedara.list_wuedara_shared_bank_expenses(
            start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
    ] == [str(snapshots["uncategorized"].id)]
    assert len(pipeline.list_snapshots(start=start, end=end, direction="")) == before


def test_manual_review_combines_native_and_xw_wm_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = XwFlowExpenseClient(AppConfig(), MagicMock(spec=SecretService))
    own = capture("own", tenant="wuedara", category="legacy")
    wm = capture("wm")
    xw = capture("xw", category="xw")
    old = capture("old", expense_date="2026-08-31")
    undated = capture("undated", expense_date=None)
    foreign = capture("foreign", tenant="wuedara")
    calls: list[str] = []

    def fetch(*, tenant_key: str, start: date, end: date, active_only: bool) -> list[FlowExpense]:
        calls.append(tenant_key)
        return [own] if tenant_key == "wuedara" else [wm, xw, old, undated, foreign]

    monkeypatch.setattr(client, "fetch", fetch)
    rows = client.fetch_for_review(tenant_key="wuedara", start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert rows == [own, wm]
    assert rows[1] is wm
    assert rows[1].attachment_ids == ("wm-attachment",)
    assert calls == ["wuedara", "xw"]

    calls.clear()
    assert client.fetch_for_review(
        tenant_key="xw", start=date(2026, 9, 1), end=date(2026, 9, 30)
    ) == [wm, xw, old, undated]
    assert calls == ["xw"]


def test_shared_manual_fetch_failure_is_not_silently_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    client = XwFlowExpenseClient(AppConfig(), MagicMock(spec=SecretService))

    def fetch(*, tenant_key: str, start: date, end: date, active_only: bool) -> list[FlowExpense]:
        if tenant_key == "xw":
            raise httpx.ConnectError("XW bridge unavailable")
        return [capture("own", tenant="wuedara")]

    monkeypatch.setattr(client, "fetch", fetch)
    with pytest.raises(httpx.ConnectError, match="XW bridge unavailable"):
        client.fetch_for_review(
            tenant_key="wuedara", start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
