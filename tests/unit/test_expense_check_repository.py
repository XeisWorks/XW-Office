"""Repository tests for Ausgaben-Check ignore rules and period shifts (SQLite in-memory)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.expense_check import ExpenseCheckRepository


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def test_add_and_list_ignore_rules(session_factory: sessionmaker[Session]) -> None:
    repo = ExpenseCheckRepository(session_factory)
    rule = repo.add_ignore_rule(
        mandant="XeisWorks",
        pattern_original="Miete Buero",
        pattern_normalized="miete buero",
        scope="forever",
    )
    assert rule.id is not None
    assert rule.created_at is not None

    rules = repo.list_ignore_rules("XeisWorks")
    assert len(rules) == 1
    assert rules[0].pattern_normalized == "miete buero"


def test_list_ignore_rules_filters_by_mandant(session_factory: sessionmaker[Session]) -> None:
    repo = ExpenseCheckRepository(session_factory)
    repo.add_ignore_rule(
        mandant="XeisWorks", pattern_original="a", pattern_normalized="a", scope="forever"
    )
    repo.add_ignore_rule(
        mandant="WuedaraMusi", pattern_original="b", pattern_normalized="b", scope="once"
    )

    assert len(repo.list_ignore_rules("XeisWorks")) == 1
    assert len(repo.list_ignore_rules("WuedaraMusi")) == 1
    assert len(repo.list_ignore_rules()) == 2


def test_remove_ignore_rule(session_factory: sessionmaker[Session]) -> None:
    repo = ExpenseCheckRepository(session_factory)
    rule = repo.add_ignore_rule(
        mandant="XeisWorks", pattern_original="a", pattern_normalized="a", scope="once"
    )

    assert repo.remove_ignore_rule(rule.id) is True
    assert repo.list_ignore_rules("XeisWorks") == []
    assert repo.remove_ignore_rule(rule.id) is False


def test_add_and_list_shift_entries(session_factory: sessionmaker[Session]) -> None:
    repo = ExpenseCheckRepository(session_factory)
    entry = repo.add_shift_entry(
        mandant="XeisWorks",
        transaction_ref="TX-1",
        source_period="2026-06",
        target_period="2026-07",
        note="Verspaetet gebucht",
    )
    assert entry.id is not None

    entries = repo.list_shift_entries("XeisWorks")
    assert len(entries) == 1
    assert entries[0].transaction_ref == "TX-1"
    assert entries[0].target_period == "2026-07"
