from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from xw_office.models.base import Base
from xw_office.models.tax_followup_dispatch import TaxFollowupDispatch
from xw_office.repositories.tax_followup_dispatch import TaxFollowupDispatchRepository
from xw_office.services.finanzonline.tax_followup_service import TaxFollowupService


def _service() -> tuple[TaxFollowupService, Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[TaxFollowupDispatch.__table__])
    session = Session(engine)
    return TaxFollowupService(TaxFollowupDispatchRepository(session)), session


def test_success_is_idempotent_for_same_recipient_and_hash() -> None:
    service, session = _service()
    calls: list[str] = []

    def send() -> None:
        calls.append("sent")

    first = service.send_once(
        filing_kind="eu_oss", period="2026-Q3", calculation_hash="a" * 64,
        recipient_kind="xw_flow_transfer", send=send,
    )
    second = service.send_once(
        filing_kind="eu_oss", period="2026-Q3", calculation_hash="a" * 64,
        recipient_kind="xw_flow_transfer", send=send,
    )
    assert first.status == "sent"
    assert second.status == "already_sent"
    assert calls == ["sent"]
    session.close()


def test_failed_delivery_can_be_retried() -> None:
    service, session = _service()
    calls = iter([RuntimeError("synthetic"), None])
    def send() -> None:
        outcome = next(calls)
        if outcome:
            raise outcome
    try:
        service.send_once(
            filing_kind="uva", period="09/2026", calculation_hash="b" * 64,
            recipient_kind="sevdesk_autobox", send=send,
        )
    except RuntimeError:
        pass
    result = service.send_once(
        filing_kind="uva", period="09/2026", calculation_hash="b" * 64,
        recipient_kind="sevdesk_autobox", send=send,
    )
    assert result.status == "sent"
    session.close()


def test_timeout_stays_pending_and_blocks_blind_retry() -> None:
    service, session = _service()
    try:
        service.send_once(
            filing_kind="uva", period="09/2026", calculation_hash="c" * 64,
            recipient_kind="xw_flow_transfer", send=lambda: (_ for _ in ()).throw(TimeoutError()),
        )
    except TimeoutError:
        pass
    try:
        service.send_once(
            filing_kind="uva", period="09/2026", calculation_hash="c" * 64,
            recipient_kind="xw_flow_transfer", send=lambda: None,
        )
    except RuntimeError as exc:
        assert "pending" in str(exc)
    else:
        raise AssertionError("Unklarer Timeout darf nicht blind wiederholt werden")
    session.close()
