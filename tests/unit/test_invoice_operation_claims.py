from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.invoice_processing.operation_claims import InvoiceOperationClaimStore
from xw_office.services.invoice_processing.service import InvoiceProcessingService


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


def test_credit_note_mail_claim_blocks_duplicate_after_success() -> None:
    repository = _repository()
    service = InvoiceProcessingService.__new__(InvoiceProcessingService)
    service._operation_claims = InvoiceOperationClaimStore(repository)

    class Mailer:
        calls = 0

        def send_mail(self, **kwargs: object) -> None:
            self.calls += 1
            attachment = kwargs["attachments"]
            assert attachment[0].content == b"pdf"  # type: ignore[index,union-attr]

        @staticmethod
        def plain_text_to_html(value: str) -> str:
            return value

    mailer = Mailer()
    service._mail_service = mailer
    kwargs = {
        "recipient": "customer@example.test",
        "credit_note_number": "G-100",
        "subject": "Gutschrift",
        "text_body": "Hallo",
        "pdf_bytes": b"pdf",
    }
    service.send_credit_note_mail("credit-100", **kwargs)

    try:
        service.send_credit_note_mail("credit-100", **kwargs)
    except RuntimeError as exc:
        assert "bereits beansprucht" in str(exc)
    else:
        raise AssertionError("duplicate credit-note mail was allowed")
    assert mailer.calls == 1


def test_unclear_credit_note_mail_result_blocks_retry() -> None:
    repository = _repository()
    service = InvoiceProcessingService.__new__(InvoiceProcessingService)
    service._operation_claims = InvoiceOperationClaimStore(repository)

    class Mailer:
        calls = 0

        def send_mail(self, **_kwargs: object) -> None:
            self.calls += 1
            raise TimeoutError("transport timed out after submission")

        @staticmethod
        def plain_text_to_html(value: str) -> str:
            return value

    mailer = Mailer()
    service._mail_service = mailer
    kwargs = {
        "recipient": "customer@example.test",
        "credit_note_number": "G-101",
        "subject": "Gutschrift",
        "text_body": "Hallo",
        "pdf_bytes": b"pdf",
    }
    for expected in ("unklar", "bereits beansprucht"):
        try:
            service.send_credit_note_mail("credit-101", **kwargs)
        except RuntimeError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("unclear credit-note mail result was retried")
    assert mailer.calls == 1

