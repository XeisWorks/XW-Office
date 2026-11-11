from __future__ import annotations

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.product_hub.sevdesk_feed_checkpoint import (
    advance_invoice_feed_checkpoint,
    resolve_invoice_feed_since,
    set_invoice_feed_start,
)


def _repository() -> SettingKvRepository:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[SettingKV.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    return SettingKvRepository(factory)


def test_invoice_feed_checkpoint_uses_default_then_persistent_overlap() -> None:
    repository = _repository()
    today = datetime.date(2026, 11, 10)

    assert resolve_invoice_feed_since(repository, today=today) == datetime.date(2026, 10, 11)
    advance_invoice_feed_checkpoint(repository, completed_through=today)

    assert resolve_invoice_feed_since(repository, today=today) == datetime.date(2026, 10, 11)


def test_invoice_feed_checkpoint_does_not_move_backwards() -> None:
    repository = _repository()
    advance_invoice_feed_checkpoint(
        repository,
        completed_through=datetime.date(2026, 11, 10),
    )
    advance_invoice_feed_checkpoint(
        repository,
        completed_through=datetime.date(2026, 11, 1),
    )

    assert resolve_invoice_feed_since(
        repository,
        today=datetime.date(2026, 11, 10),
    ) == datetime.date(2026, 10, 11)


def test_explicit_since_overrides_persistent_checkpoint() -> None:
    repository = _repository()
    explicit = datetime.date(2020, 1, 2)

    assert resolve_invoice_feed_since(
        repository,
        requested_since=explicit,
        today=datetime.date(2026, 11, 10),
    ) == explicit


def test_invalid_persistent_checkpoint_fails_closed() -> None:
    repository = _repository()
    repository.set_value_json("product_hub.sevdesk_invoice_feed_checkpoint.v1", "not-json")

    with pytest.raises(RuntimeError, match="Wasserstand ist ungueltig"):
        resolve_invoice_feed_since(repository, today=datetime.date(2026, 11, 10))


def test_inventory_cutover_start_clamps_overlap_and_explicit_backfills() -> None:
    repository = _repository()
    set_invoice_feed_start(repository, first_eligible_date=datetime.date(2026, 11, 5))

    assert resolve_invoice_feed_since(repository, today=datetime.date(2026, 11, 10)) == datetime.date(2026, 11, 5)
    assert resolve_invoice_feed_since(
        repository,
        requested_since=datetime.date(2020, 1, 1),
        today=datetime.date(2026, 11, 10),
    ) == datetime.date(2026, 11, 5)


def test_invalid_inventory_cutover_start_fails_closed() -> None:
    repository = _repository()
    repository.set_value_json("product_hub.sevdesk_invoice_feed_start.v1", "not-json")

    with pytest.raises(RuntimeError, match="Stichtag ist ungueltig"):
        resolve_invoice_feed_since(repository, today=datetime.date(2026, 11, 10))
