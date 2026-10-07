"""Tests for ExpenseAuditService classification, ignore rules, and shifts."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.expense_check import ExpenseCheckRepository
from xw_office.repositories.expense_pipeline import ExpensePipelineRepository
from xw_office.services.expenses.bank_provider import (
    BankDocumentLink,
    BankExpense,
    DocumentLinkScan,
    SevdeskExpenseProvider,
)
from xw_office.services.expenses.service import ExpenseAction, ExpenseAuditService, ExpenseRow


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

    def __init__(self, rows: list[BankExpense], scan: DocumentLinkScan | None = None) -> None:
        self.rows = rows
        self.scan = scan or DocumentLinkScan((), True)

    def find_account(self) -> SimpleNamespace:
        return SimpleNamespace(id="XEISWORKS")

    def fetch(self, start: date, end: date, *, outgoing_only: bool = True) -> tuple[SimpleNamespace, list[BankExpense]]:
        return self.find_account(), self.rows

    def resolve_document_links(
        self, start: date, end: date, *, account_id: str | None = None
    ) -> DocumentLinkScan:
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
    assert cached.documents[0].url.endswith("/fi/detail/type/VB/id/V-7")
    assert cached.document_link_scan_complete is False


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
