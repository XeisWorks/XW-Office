from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.invoice_processing.operation_claims import InvoiceOperationClaimStore


def _repository() -> SettingKvRepository:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[SettingKV.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    return SettingKvRepository(factory)


def test_claim_is_shared_between_store_instances_and_blocks_replay() -> None:
    repository = _repository()
    first_store = InvoiceOperationClaimStore(repository)
    claim = first_store.acquire("invoice-1", "invoice_mail")
    assert claim.acquired is True
    assert claim.state == "running"

    second_store = InvoiceOperationClaimStore(repository)
    competing = second_store.acquire("invoice-1", "invoice_mail")
    assert competing.acquired is False
    assert competing.operation_id == claim.operation_id

    assert first_store.finish(claim, "succeeded") is True
    replay = second_store.acquire("invoice-1", "invoice_mail")
    assert replay.acquired is False
    assert replay.state == "succeeded"


def test_failed_claim_can_retry_with_the_same_operation_id() -> None:
    repository = _repository()
    store = InvoiceOperationClaimStore(repository)
    claim = store.acquire("invoice-2", "invoice_mail")
    assert store.finish(claim, "failed", error="confirmed unsent") is True

    retry = InvoiceOperationClaimStore(repository).acquire("invoice-2", "invoice_mail")

    assert retry.acquired is True
    assert retry.operation_id == claim.operation_id


def test_unknown_claim_blocks_automatic_retry() -> None:
    repository = _repository()
    store = InvoiceOperationClaimStore(repository)
    claim = store.acquire("invoice-3", "invoice_mail")
    assert store.finish(claim, "unknown", error="sevDesk readback timeout") is True

    retry = InvoiceOperationClaimStore(repository).acquire("invoice-3", "invoice_mail")

    assert retry.acquired is False
    assert retry.state == "unknown"

