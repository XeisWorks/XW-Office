"""Tests for ExpenseAuditService classification, ignore rules, and shifts."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.expense_check import ExpenseCheckRepository
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
