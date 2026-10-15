"""Tests for ExpenseAuditService classification, ignore rules, and shifts."""
from __future__ import annotations

import json
import datetime
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.expense_check import ExpenseCheckRepository
from xw_office.repositories.expense_pipeline import ExpensePipelineRepository
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.expenses.bank_provider import (
    BankDocumentLink,
    BankExpense,
    DocumentLinkScan,
    SevdeskExpenseProvider,
)
from xw_office.services.expenses.service import ExpenseAction, ExpenseAuditService, ExpenseRow
from xw_office.services.expenses import service as expense_service_module


class _SettingsRepoStub:
    """In-memory stand-in for SettingKvRepository, mirroring its interface."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._store: dict[str, str] = dict(initial or {})

    def get_value_json(self, key: str) -> str | None:
        return self._store.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self._store[key] = value_json

    def mutate_value_json(self, key: str, mutator: object) -> str:
        current = self._store.get(key)
        updated = mutator(current)  # type: ignore[operator]
        self._store[key] = updated
        return updated


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def test_list_open_and_filter_rows_unchanged(session_factory: sessionmaker[Session]) -> None:
    repo = _SettingsRepoStub(
        {
            "expenses.open_items": json.dumps(
                [
                    {"ref": "B-1", "supplier": "Buerobedarf", "gross_amount": "10.00", "status": "open"},
                    {"ref": "B-2", "supplier": "Strom AG", "gross_amount": "50.00", "status": "open"},
                ]
            )
        }
    )
    svc = ExpenseAuditService(repo)  # type: ignore[arg-type]
    rows = svc.list_open()
    assert len(rows) == 2
    filtered = svc.filter_rows(rows, needle="strom")
    assert len(filtered) == 1
    assert filtered[0].ref == "B-2"


def test_add_ignore_rule_and_is_ignored_matches_varying_reference(
    session_factory: sessionmaker[Session],
) -> None:
    expense_repo = ExpenseCheckRepository(session_factory)
    svc = ExpenseAuditService(expense_check_repo=expense_repo)

    svc.add_ignore_rule(mandant="XeisWorks", purpose_text="Miete Buero RE 100234", scope="forever")

    # Same recurring payment next month, only the invoice number differs.
    matched = svc.is_ignored("Miete Buero RE 100999", mandant="XeisWorks")
    assert matched is not None
    assert matched.scope == "forever"

    not_matched = svc.is_ignored("Voellig andere Zahlung", mandant="XeisWorks")
    assert not_matched is None


def test_add_ignore_rule_rejects_unknown_scope(session_factory: sessionmaker[Session]) -> None:
    expense_repo = ExpenseCheckRepository(session_factory)
    svc = ExpenseAuditService(expense_check_repo=expense_repo)
    with pytest.raises(ValueError):
        svc.add_ignore_rule(mandant="XeisWorks", purpose_text="Miete", scope="sometimes")


def test_remove_ignore_rule(session_factory: sessionmaker[Session]) -> None:
    expense_repo = ExpenseCheckRepository(session_factory)
    svc = ExpenseAuditService(expense_check_repo=expense_repo)
    rule = svc.add_ignore_rule(mandant="XeisWorks", purpose_text="Miete Buero", scope="once")
    assert svc.remove_ignore_rule(rule.id) is True
    assert svc.list_ignore_rules("XeisWorks") == []


def test_shift_period_validates_period_format(session_factory: sessionmaker[Session]) -> None:
    expense_repo = ExpenseCheckRepository(session_factory)
    svc = ExpenseAuditService(expense_check_repo=expense_repo)
    with pytest.raises(ValueError):
        svc.shift_period(
            mandant="XeisWorks",
            transaction_ref="TX-1",
            source_period="2026-6",
            target_period="2026-07",
        )


def test_classify_rows_marks_shifted_and_ignored_and_open(
    session_factory: sessionmaker[Session],
) -> None:
    expense_repo = ExpenseCheckRepository(session_factory)
    svc = ExpenseAuditService(expense_check_repo=expense_repo)

    svc.add_ignore_rule(mandant="XeisWorks", purpose_text="Bankgebuehr Kontofuehrung", scope="forever")
    svc.shift_period(
        mandant="XeisWorks",
        transaction_ref="TX-42",
        source_period="2026-06",
        target_period="2026-07",
    )

    rows = [
        ExpenseRow(ref="TX-42", supplier="Post", gross_amount="5.00", category="", status="open", note=""),
        ExpenseRow(
            ref="TX-2",
            supplier="Bankgebuehr",
            gross_amount="3.50",
            category="",
            status="open",
            note="Kontofuehrung Maerz",
        ),
        ExpenseRow(ref="TX-3", supplier="Buerobedarf", gross_amount="20.00", category="", status="open", note=""),
    ]

    result = svc.classify_rows(rows, mandant="XeisWorks", period="2026-06")

    by_ref = {c.row.ref: c for c in result}
    assert by_ref["TX-42"].effective_status == "shifted"
    assert by_ref["TX-2"].effective_status == "ignored"
    assert by_ref["TX-3"].effective_status == "open"


def test_apply_action_ignore_forever_persists_rule(session_factory: sessionmaker[Session]) -> None:
    expense_repo = ExpenseCheckRepository(session_factory)
    svc = ExpenseAuditService(expense_check_repo=expense_repo)
    row = ExpenseRow(ref="TX-9", supplier="Telefon AG", gross_amount="12.00", category="", status="open", note="")

    result = svc.apply_action(ExpenseAction.IGNORE_FOREVER, row, mandant="XeisWorks")

    assert result is not None
    assert svc.list_ignore_rules("XeisWorks")


def test_apply_action_shift_requires_target_period(session_factory: sessionmaker[Session]) -> None:
    expense_repo = ExpenseCheckRepository(session_factory)
    svc = ExpenseAuditService(expense_check_repo=expense_repo)
    row = ExpenseRow(ref="TX-9", supplier="Telefon AG", gross_amount="12.00", category="", status="open", note="")
    with pytest.raises(ValueError):
        svc.apply_action(ExpenseAction.SHIFT, row, mandant="XeisWorks", source_period="2026-06")


def test_apply_action_flag_updates_open_items_atomically() -> None:
    repo = _SettingsRepoStub(
        {
            "expenses.open_items": json.dumps(
                [{"ref": "B-1", "supplier": "Buerobedarf", "gross_amount": "10.00", "status": "open"}]
            )
        }
    )
    svc = ExpenseAuditService(repo)  # type: ignore[arg-type]
    row = ExpenseRow(ref="B-1", supplier="Buerobedarf", gross_amount="10.00", category="", status="open", note="")

    result = svc.apply_action(ExpenseAction.FLAG, row, note="Bitte pruefen")

    assert result is None
    rows = svc.list_open()
    assert rows[0].status == "flagged"
    assert rows[0].note == "Bitte pruefen"


def test_ignore_rule_actions_without_db_raise() -> None:
    svc = ExpenseAuditService(None)
    with pytest.raises(RuntimeError):
        svc.add_ignore_rule(mandant="X", purpose_text="Miete", scope="once")
    assert svc.list_ignore_rules() == []
    assert svc.remove_ignore_rule(str("00000000-0000-0000-0000-000000000000")) is False


def test_profile_rule_matches_derived_card_merchant() -> None:
    row = BankExpense(
        external_id="TX-GITHUB",
        account_id="XEISWORKS",
        value_date=date(2026, 9, 4),
        entry_date=None,
        amount=Decimal("-23.10"),
        currency="EUR",
        direction="outgoing",
        payee_name="",
        payee_normalized="",
        counterparty_iban="",
        payment_reference="",
        purpose=(
            "Bezahlung Karte MC/000008551E-COMM 25,16 USD D002 04.09. 04:34"
            "GITHUB, INC.\\SAN FRANCISCO\\94SPESEN: 1,25"
        ),
        sevdesk_status="",
    )
    rule = SimpleNamespace(match_field="payee", value_normalized="github inc")

    assert ExpenseAuditService._match_profile_rule(row, "musikheroes", [rule]) == (
        "candidate",
        "musikheroes:payee",
    )


def _bank_row(*, external_id: str = "TX-1", purpose: str = "Hosting MusikHeroes") -> BankExpense:
    return BankExpense(
        external_id=external_id,
        account_id="XEISWORKS",
        value_date=date(2026, 9, 4),
        entry_date=date(2026, 9, 4),
        amount=Decimal("-23.10"),
        currency="EUR",
        direction="outgoing",
        payee_name="Hosting GmbH",
        payee_normalized="hosting gmbh",
        counterparty_iban="AT001234",
        payment_reference="RE 123",
        purpose=purpose,
        sevdesk_status="",
    )


class _BankProviderStub:
    base_url = "https://my.sevdesk.de/api/v1"

    def __init__(
        self,
        rows: list[BankExpense],
        scan: DocumentLinkScan | None = None,
        *,
        account_id: str = "XEISWORKS",
    ) -> None:
        self.rows = rows
        self.scan = scan or DocumentLinkScan((), True)
        self.account_id = account_id
        self.fetch_calls = 0
        self.resolve_calls = 0

    def find_account(self) -> SimpleNamespace:
        return SimpleNamespace(id=self.account_id)

    def fetch(self, start: date, end: date, *, outgoing_only: bool = True) -> tuple[SimpleNamespace, list[BankExpense]]:
        self.fetch_calls += 1
        return self.find_account(), self.rows

    def resolve_document_links(
        self,
        start: date,
        end: date,
        *,
        account_id: str | None = None,
        cached_fingerprints: object | None = None,
        retry_cached_documents: object | None = None,
        force: bool = False,
    ) -> DocumentLinkScan:
        self.resolve_calls += 1
        return self.scan


def test_position_rule_assigns_only_unique_composite_match(
    session_factory: sessionmaker[Session],
) -> None:
    pipeline = ExpensePipelineRepository(session_factory)
    service = ExpenseAuditService(
        bank_provider=_BankProviderStub([_bank_row()]),  # type: ignore[arg-type]
        pipeline_repo=pipeline,
    )
    assert {item.key for item in service.list_positions()} == {"xw", "mh", "wm", "bh", "priv"}
    pipeline.add_position_rule(
        position_key="mh",
        payee_normalized="hosting gmbh",
        purpose_contains="musikheroes",
    )

    rows = service.list_bank_expenses(start=date(2026, 9, 1), end=date(2026, 9, 30))

    assert rows[0].position_key == "mh"
    assert rows[0].position_source == "automatic"


def test_ambiguous_rules_do_not_assign_and_manual_assignment_wins(
    session_factory: sessionmaker[Session],
) -> None:
    pipeline = ExpensePipelineRepository(session_factory)
    provider = _BankProviderStub([_bank_row()])
    service = ExpenseAuditService(bank_provider=provider, pipeline_repo=pipeline)  # type: ignore[arg-type]
    service.list_positions()
    pipeline.add_position_rule(position_key="mh", payee_normalized="hosting gmbh")
    pipeline.add_position_rule(position_key="xw", counterparty_iban="AT001234")

    first = service.list_bank_expenses(start=date(2026, 9, 1), end=date(2026, 9, 30))[0]
    assert first.position_key == ""

    service.assign_transaction_position(transaction_id=first.transaction_id, position_key="wm")
    second = service.list_bank_expenses(start=date(2026, 9, 1), end=date(2026, 9, 30))[0]
    assert second.position_key == "wm"
    assert second.position_source == "manual"


def test_document_link_is_persisted_and_reused_from_cache(
    session_factory: sessionmaker[Session],
) -> None:
    pipeline = ExpensePipelineRepository(session_factory)
    scan = DocumentLinkScan(
        (
            BankDocumentLink(
                transaction_external_id="TX-1",
                resource_type="Voucher",
                external_id="V-7",
                document_number="VB 2026-7",
            ),
        ),
        True,
    )
    provider = _BankProviderStub([_bank_row()], scan)
    service = ExpenseAuditService(bank_provider=provider, pipeline_repo=pipeline)  # type: ignore[arg-type]

    live = service.list_bank_expenses(start=date(2026, 9, 1), end=date(2026, 9, 30))[0]
    provider.scan = DocumentLinkScan((), False, 1)
    cached = service.list_bank_expenses(
        start=date(2026, 9, 1), end=date(2026, 9, 30), refresh=False
    )[0]

    assert live.documents[0].document_number == "VB 2026-7"
    assert cached.documents[0].url.endswith("/ex/detail/id/V-7")
    assert cached.document_link_scan_complete is True


@pytest.mark.parametrize("empty", [False, True])
def test_shared_sync_reuses_fresh_cache_across_service_instances(
    session_factory: sessionmaker[Session], empty: bool
) -> None:
    pipeline = ExpensePipelineRepository(session_factory)
    settings = SettingKvRepository(session_factory)
    provider = _BankProviderStub([] if empty else [_bank_row()])
    first_pc = ExpenseAuditService(
        settings, bank_provider=provider, pipeline_repo=pipeline  # type: ignore[arg-type]
    )
    second_pc = ExpenseAuditService(
        SettingKvRepository(session_factory),
        bank_provider=provider, pipeline_repo=ExpensePipelineRepository(session_factory),  # type: ignore[arg-type]
    )
    period = {"start": date(2026, 9, 1), "end": date(2026, 9, 30)}
    first = first_pc.synchronize_bank_expenses(**period)
    second = second_pc.synchronize_bank_expenses(**period)
    assert provider.fetch_calls == 1
    assert provider.resolve_calls == 1
    assert first.refreshed and not second.refreshed
    assert first.synced_at == second.synced_at
    assert first.document_scan_complete and second.document_scan_complete
    assert [row.transaction_id for row in first.rows] == [row.transaction_id for row in second.rows]


def test_shared_sync_expires_and_manual_refresh_bypasses_freshness(
    session_factory: sessionmaker[Session],
) -> None:
    settings = SettingKvRepository(session_factory)
    provider = _BankProviderStub([_bank_row()])
    service = ExpenseAuditService(
        settings, bank_provider=provider, pipeline_repo=ExpensePipelineRepository(session_factory),  # type: ignore[arg-type]
    )
    period = {"start": date(2026, 9, 1), "end": date(2026, 9, 30)}
    service.synchronize_bank_expenses(**period)
    manual = service.synchronize_bank_expenses(**period, force=True)
    assert manual.refreshed
    assert provider.fetch_calls == provider.resolve_calls == 2
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=6)
    settings.set_value_json(
        "expenses.sync.xw", json.dumps({"periods": {"2026-09-01/2026-09-30": old.isoformat()}})
    )
    service.synchronize_bank_expenses(**period)
    assert provider.fetch_calls == provider.resolve_calls == 3


@pytest.mark.parametrize("age_seconds, refreshed", [(299, False), (300, True), (-1, True)])
def test_shared_cache_freshness_boundary_is_exactly_five_minutes(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
    age_seconds: int, refreshed: bool,
) -> None:
    settings = SettingKvRepository(session_factory)
    provider = _BankProviderStub([_bank_row()])
    service = ExpenseAuditService(
        settings, bank_provider=provider, pipeline_repo=ExpensePipelineRepository(session_factory),  # type: ignore[arg-type]
    )
    period = {"start": date(2026, 9, 1), "end": date(2026, 9, 30)}
    service.list_bank_expenses(**period)
    now = datetime.datetime(2026, 10, 15, 18, 0, tzinfo=datetime.UTC)
    cached_at = now - datetime.timedelta(seconds=age_seconds)
    settings.set_value_json(
        "expenses.sync.xw",
        json.dumps({"periods": {"2026-09-01/2026-09-30": cached_at.isoformat()}}),
    )
    monkeypatch.setattr(
        expense_service_module, "datetime",
        SimpleNamespace(
            datetime=SimpleNamespace(now=lambda tz: now),
            timedelta=datetime.timedelta, UTC=datetime.UTC,
        ),
    )
    result = service.synchronize_bank_expenses(**period)
    assert result.refreshed is refreshed
    assert provider.fetch_calls == provider.resolve_calls == (2 if refreshed else 1)


def test_shared_sync_is_scoped_by_tenant_and_period(
    session_factory: sessionmaker[Session],
) -> None:
    settings = SettingKvRepository(session_factory)
    providers = {
        "xw": _BankProviderStub([_bank_row()]),
        "wuedara": _BankProviderStub([_bank_row()], account_id="WUEDARA"),
    }
    service = ExpenseAuditService(
        settings, pipeline_repo=ExpensePipelineRepository(session_factory),
        tenant_providers=providers,  # type: ignore[arg-type]
    )
    service.synchronize_bank_expenses(start=date(2026, 9, 1), end=date(2026, 9, 30))
    service.for_tenant("wuedara").synchronize_bank_expenses(
        start=date(2026, 9, 1), end=date(2026, 9, 30)
    )
    service.synchronize_bank_expenses(start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert providers["xw"].fetch_calls == providers["xw"].resolve_calls == 2
    assert providers["wuedara"].fetch_calls == providers["wuedara"].resolve_calls == 1
    assert settings.get_value_json("expenses.sync.xw") is not None
    assert settings.get_value_json("expenses.sync.wuedara") is not None


@pytest.mark.parametrize("empty", [False, True])
def test_partial_sync_never_marks_period_fresh(
    session_factory: sessionmaker[Session], empty: bool
) -> None:
    provider = _BankProviderStub([] if empty else [_bank_row()], DocumentLinkScan((), False, 1))
    service = ExpenseAuditService(
        SettingKvRepository(session_factory), bank_provider=provider,  # type: ignore[arg-type]
        pipeline_repo=ExpensePipelineRepository(session_factory),
    )
    period = {"start": date(2026, 9, 1), "end": date(2026, 9, 30)}
    partial = service.synchronize_bank_expenses(**period)
    assert not partial.document_scan_complete
    assert partial.synced_at is None
    provider.scan = DocumentLinkScan((), True)
    complete = service.synchronize_bank_expenses(**period)
    assert complete.refreshed and complete.document_scan_complete
    assert complete.synced_at is not None
    assert provider.fetch_calls == provider.resolve_calls == 2


def test_failed_sync_preserves_cache_and_does_not_store_freshness(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _BankProviderStub([_bank_row()])
    settings = SettingKvRepository(session_factory)
    service = ExpenseAuditService(
        settings, bank_provider=provider, pipeline_repo=ExpensePipelineRepository(session_factory),  # type: ignore[arg-type]
    )
    period = {"start": date(2026, 9, 1), "end": date(2026, 9, 30)}
    service.list_bank_expenses(**period)

    def fail_fetch(*args: object, **kwargs: object) -> object:
        raise RuntimeError("sevDesk unavailable")

    monkeypatch.setattr(provider, "fetch", fail_fetch)
    with pytest.raises(RuntimeError, match="sevDesk unavailable"):
        service.synchronize_bank_expenses(**period)
    assert settings.get_value_json("expenses.sync.xw") is None
    assert len(service.list_bank_expenses(**period, refresh=False)) == 1


def test_waiting_manual_sync_reuses_scan_completed_by_other_pc(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = SettingKvRepository(session_factory)
    provider = _BankProviderStub([_bank_row()])
    service = ExpenseAuditService(
        settings, bank_provider=provider, pipeline_repo=ExpensePipelineRepository(session_factory),  # type: ignore[arg-type]
    )
    service.list_bank_expenses(start=date(2026, 9, 1), end=date(2026, 9, 30))

    def after_waiting_for_lock(key: str, mutator: Callable[[str | None], str]) -> str:
        # Simulate the other PC committing its successful scan before releasing the lock.
        finished = datetime.datetime.now(datetime.UTC)
        return mutator(json.dumps({"periods": {"2026-09-01/2026-09-30": finished.isoformat()}}))

    monkeypatch.setattr(settings, "mutate_value_json", after_waiting_for_lock)
    result = service.synchronize_bank_expenses(
        start=date(2026, 9, 1), end=date(2026, 9, 30), force=True
    )
    assert not result.refreshed
    assert provider.fetch_calls == provider.resolve_calls == 1


def test_shared_sync_holds_postgres_tenant_lock_across_scan(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = SettingKvRepository(session_factory)
    connection = MagicMock(spec=Session)
    connection.get_bind.return_value.dialect.name = "postgresql"
    connection.get.return_value = None
    order: list[str] = []
    connection.execute.side_effect = lambda *args: order.append("locked")

    @contextmanager
    def scope() -> Generator[Session, None, None]:
        try:
            yield connection
        finally:
            order.append("released")

    monkeypatch.setattr(settings, "_scope", scope)
    provider = _BankProviderStub([_bank_row()])
    original_fetch = provider.fetch

    def fetch(start: date, end: date, *, outgoing_only: bool = True) -> tuple[SimpleNamespace, list[BankExpense]]:
        order.append("fetch")
        return original_fetch(start, end, outgoing_only=outgoing_only)

    monkeypatch.setattr(provider, "fetch", fetch)
    service = ExpenseAuditService(
        settings, bank_provider=provider, pipeline_repo=ExpensePipelineRepository(session_factory),  # type: ignore[arg-type]
    )
    service.synchronize_bank_expenses(start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert order == ["locked", "fetch", "released"]
    statement, parameters = connection.execute.call_args.args
    assert "pg_advisory_xact_lock" in str(statement)
    assert parameters == {"key": "expenses.sync.xw"}


def test_failed_rescan_invalidates_previously_fresh_period(
    session_factory: sessionmaker[Session],
) -> None:
    provider = _BankProviderStub([_bank_row()])
    service = ExpenseAuditService(
        SettingKvRepository(session_factory), bank_provider=provider,  # type: ignore[arg-type]
        pipeline_repo=ExpensePipelineRepository(session_factory),
    )
    period = {"start": date(2026, 9, 1), "end": date(2026, 9, 30)}
    service.synchronize_bank_expenses(**period)
    provider.scan = DocumentLinkScan((), False, 1)
    partial = service.synchronize_bank_expenses(**period, force=True)
    assert partial.synced_at is None
    provider.scan = DocumentLinkScan((), True)
    retried = service.synchronize_bank_expenses(**period)
    assert retried.refreshed and retried.document_scan_complete
    assert provider.resolve_calls == 3


def test_document_link_refresh_uses_cached_transactions_without_bank_reload(
    session_factory: sessionmaker[Session],
) -> None:
    pipeline = ExpensePipelineRepository(session_factory)
    provider = _BankProviderStub([_bank_row()])
    service = ExpenseAuditService(bank_provider=provider, pipeline_repo=pipeline)  # type: ignore[arg-type]
    start = date(2026, 9, 1)
    end = date(2026, 9, 30)

    service.list_bank_expenses(start=start, end=end)
    provider.scan = DocumentLinkScan(
        (
            BankDocumentLink(
                transaction_external_id="TX-1",
                resource_type="Voucher",
                external_id="V-8",
                document_number="VB 2026-8",
            ),
        ),
        True,
    )
    provider.fetch_calls = 0
    provider.resolve_calls = 0

    rows = service.list_bank_expenses(
        start=start,
        end=end,
        refresh=False,
        refresh_document_links=True,
        outgoing_only=False,
    )

    assert provider.fetch_calls == 0
    assert provider.resolve_calls == 1
    assert rows[0].documents[0].document_number == "VB 2026-8"


def test_bank_expenses_can_include_incoming_transactions_for_receipt_review(
    session_factory: sessionmaker[Session],
) -> None:
    pipeline = ExpensePipelineRepository(session_factory)
    income = replace(
        _bank_row(external_id="TX-2", purpose="Erlös"),
        amount=Decimal("42.00"),
        direction="incoming",
    )
    service = ExpenseAuditService(
        bank_provider=_BankProviderStub([_bank_row(), income]),  # type: ignore[arg-type]
        pipeline_repo=pipeline,
    )

    rows = service.list_bank_expenses(
        start=date(2026, 9, 1), end=date(2026, 9, 30), outgoing_only=False
    )

    assert [row.amount for row in rows] == [Decimal("-23.10"), Decimal("42.00")]


def test_purpose_rule_removes_boilerplate_for_matching_payee_only(
    session_factory: sessionmaker[Session],
) -> None:
    pipeline = ExpensePipelineRepository(session_factory)
    row = replace(
        _bank_row(
            purpose="Vorschreibung 3. Quartal 2026 - Auf die Buchungen im SVS-Kontoauszug wird verwiesen"
        ),
        payee_name="SVS",
        payee_normalized="svs",
        payment_reference="",
    )
    service = ExpenseAuditService(
        bank_provider=_BankProviderStub(
            [row, replace(row, external_id="TX-2", payee_name="Andere GmbH", payee_normalized="andere gmbh")]
        ),  # type: ignore[arg-type]
        pipeline_repo=pipeline,
    )
    service.add_purpose_rule(
        payee="SVS",
        remove_text="Auf die Buchungen im SVS-Kontoauszug wird verwiesen",
    )

    displayed = service.list_bank_expenses(
        start=date(2026, 9, 1), end=date(2026, 9, 30)
    )

    assert displayed[0].purpose == "Vorschreibung 3. Quartal 2026"
    assert displayed[0].raw_purpose.endswith("wird verwiesen")
    assert displayed[1].purpose.endswith("wird verwiesen")


def test_wuedara_tenant_keeps_positions_rules_and_links_separate(
    session_factory: sessionmaker[Session],
) -> None:
    pipeline = ExpensePipelineRepository(session_factory)
    xw_provider = _BankProviderStub([_bank_row()])
    wuedara_provider = _BankProviderStub(
        [replace(_bank_row(), purpose="Hosting Rechnung - Bitte entfernen")],
        account_id="WUEDARA",
    )
    service = ExpenseAuditService(
        bank_provider=xw_provider,  # type: ignore[arg-type]
        pipeline_repo=pipeline,
        tenant_providers={"xw": xw_provider, "wuedara": wuedara_provider},  # type: ignore[dict-item]
    )
    wuedara = service.for_tenant("wuedara")

    assert {item.key for item in wuedara.list_positions()} == {"xw", "mh", "wm", "bh", "priv"}
    wuedara.add_position_rule(position_key="wm", payee="Hosting GmbH")
    wuedara.add_purpose_rule(payee="Hosting GmbH", remove_text="Bitte entfernen")
    wuedara.add_supplier_link(
        payee="Hosting GmbH",
        iban="AT001234",
        label="Wüdara Portal",
        url="https://example.test/wuedara",
    )

    wuedara_rows = wuedara.list_bank_expenses(start=date(2026, 9, 1), end=date(2026, 9, 30))
    xw_rows = service.list_bank_expenses(start=date(2026, 9, 1), end=date(2026, 9, 30))

    assert wuedara_rows[0].position_key == "wm"
    assert wuedara_rows[0].supplier_url == "https://example.test/wuedara"
    assert xw_rows[0].position_key == ""
    assert service.list_purpose_rules() == []
    assert len(wuedara.list_purpose_rules()) == 1
    assert service.list_supplier_links() == []


def test_document_resolver_uses_typed_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Response:
        @staticmethod
        def json() -> dict[str, object]:
            return {
                "objects": [
                    {"id": "TX-1", "checkAccount": {"id": "XEISWORKS"}}
                ]
            }

    class _Connection:
        def get(self, path: str) -> _Response:
            calls.append(path)
            return _Response()

    provider = SevdeskExpenseProvider(_Connection())  # type: ignore[arg-type]

    def fake_list(path: str, *, params: dict[str, object] | None = None) -> list[dict[str, object]]:
        if path == "/Voucher":
            return [{"id": "V-7", "voucherDate": "2026-09-05", "voucherNumber": "VB 7"}]
        return []

    monkeypatch.setattr(provider, "_list", fake_list)

    scan = provider.resolve_document_links(
        date(2026, 9, 1), date(2026, 9, 30), account_id="XEISWORKS"
    )

    assert scan.complete is True
    assert scan.links[0].document_number == "VB 7"
    assert calls == ["/Voucher/V-7/getCheckAccountTransactions"]


def test_document_resolver_skips_unchanged_cached_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Response:
        @staticmethod
        def json() -> dict[str, object]:
            return {"objects": []}

    class _Connection:
        def get(self, path: str) -> _Response:
            calls.append(path)
            return _Response()

    provider = SevdeskExpenseProvider(_Connection())  # type: ignore[arg-type]

    def fake_list(path: str, *, params: dict[str, object] | None = None) -> list[dict[str, object]]:
        if path == "/Voucher":
            return [{"id": "V-7", "voucherDate": "2026-09-05", "voucherNumber": "VB 7"}]
        return []

    monkeypatch.setattr(provider, "_list", fake_list)
    first = provider.resolve_document_links(
        date(2026, 9, 1), date(2026, 9, 30), account_id="XEISWORKS"
    )
    cached_fingerprints = {
        (document.resource_type, document.external_id): document.fingerprint
        for document in first.scanned_documents
    }
    calls.clear()

    second = provider.resolve_document_links(
        date(2026, 9, 1),
        date(2026, 9, 30),
        account_id="XEISWORKS",
        cached_fingerprints=cached_fingerprints,
    )

    assert first.resolved_document_count == 1
    assert second.links == ()
    assert second.cached_document_count == 1
    assert second.resolved_document_count == 0
    assert calls == []

    retried = provider.resolve_document_links(
        date(2026, 9, 1),
        date(2026, 9, 30),
        account_id="XEISWORKS",
        cached_fingerprints=cached_fingerprints,
        retry_cached_documents=set(cached_fingerprints),
    )

    assert retried.resolved_document_count == 1
    assert calls == ["/Voucher/V-7/getCheckAccountTransactions"]
