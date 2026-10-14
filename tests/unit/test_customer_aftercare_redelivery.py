from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.customer_aftercare import (
    CustomerAftercareItemInput,
    CustomerAftercareRepository,
)


def _repo() -> CustomerAftercareRepository:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return CustomerAftercareRepository(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    )


def _waiting_case(repo: CustomerAftercareRepository, *, case_type: str = "MANUAL_REDELIVERY"):
    reservation = repo.create_invoice_case(
        invoice_id=str(uuid.uuid4()),
        invoice_number="RE-260001",
        order_number="21842",
        sevdesk_contact_id="contact-1",
        wix_contact_id="wix-contact-1",
        customer_email="kunde@example.test",
        address_lines=["Kunde", "Musterstraße 1", "8912 Admont"],
        items=[CustomerAftercareItemInput(role="MISSING_TO_SEND", sku="XW-1", name="Notenheft", quantity=1)],
    )
    case = repo.confirm_classification(
        reservation.case.id,
        case_type=case_type,
        courtesy=True,
        customer_type="",
        wait_for_next_order=True,
        due_at=None,
        trigger_now=False,
    )
    assert case is not None
    return case


def test_claim_is_atomic_and_retryable_after_release() -> None:
    repo = _repo()
    case = _waiting_case(repo)

    first = repo.claim_for_invoice(
        invoice_id="target-1",
        invoice_number="RE-260002",
        sevdesk_contact_id="contact-1",
        wix_contact_id="wix-contact-1",
        customer_email="kunde@example.test",
    )
    assert [row.id for row in first] == [case.id]
    assert first[0].dispatch_status == "PRINTING"

    # A concurrent/repeated START must not claim the same printing case again.
    assert repo.claim_for_invoice(
        invoice_id="target-1",
        invoice_number="RE-260002",
        sevdesk_contact_id="contact-1",
        wix_contact_id="wix-contact-1",
        customer_email="kunde@example.test",
    ) == []

    repo.release_invoice_claim_for_invoice("target-1")
    retry = repo.claim_for_invoice(
        invoice_id="target-1",
        invoice_number="RE-260002",
        sevdesk_contact_id="contact-1",
        wix_contact_id="wix-contact-1",
        customer_email="kunde@example.test",
    )
    assert [row.id for row in retry] == [case.id]


def test_confirmed_mail_case_is_eligible_for_redelivery_claim() -> None:
    repo = _repo()
    case = _waiting_case(repo, case_type="B2B_MISSING_ITEMS")
    claimed = repo.claim_for_invoice(
        invoice_id="target-2",
        invoice_number="RE-260003",
        sevdesk_contact_id="contact-1",
    )
    assert [row.id for row in claimed] == [case.id]
