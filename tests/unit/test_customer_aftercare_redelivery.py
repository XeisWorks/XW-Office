from __future__ import annotations

import datetime
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
        items=[
            CustomerAftercareItemInput(
                role="MISSING_TO_SEND", sku="XW-1", name="Notenheft", quantity=1
            )
        ],
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
    assert (
        repo.claim_for_invoice(
            invoice_id="target-1",
            invoice_number="RE-260002",
            sevdesk_contact_id="contact-1",
            wix_contact_id="wix-contact-1",
            customer_email="kunde@example.test",
        )
        == []
    )

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


def test_timed_snooze_is_respected_even_when_customer_has_new_invoice() -> None:
    repo = _repo()
    case = _waiting_case(repo)
    now = datetime.datetime.now(datetime.timezone.utc)
    repo.snooze_case(
        case.id,
        mode="UNTIL_DATE",
        until=now + datetime.timedelta(days=2),
        reason="Kunde wartet",
    )

    assert (
        repo.claim_for_invoice(
            invoice_id="target-snoozed",
            invoice_number="RE-260010",
            sevdesk_contact_id="contact-1",
        )
        == []
    )

    assert repo.release_snoozes(now=now + datetime.timedelta(days=3))[0].id == case.id
    claimed = repo.claim_for_invoice(
        invoice_id="target-after-snooze",
        invoice_number="RE-260011",
        sevdesk_contact_id="contact-1",
    )
    assert [row.id for row in claimed] == [case.id]


def test_next_start_snooze_is_released_only_for_following_start() -> None:
    repo = _repo()
    case = _waiting_case(repo)
    repo.snooze_case(case.id, mode="NEXT_START", reason="Dieser Lauf nicht")

    assert repo.claim_for_invoice(
        invoice_id="same-run",
        invoice_number="RE-260020",
        sevdesk_contact_id="contact-1",
    ) == []

    released = repo.release_snoozes(mode="NEXT_START")
    assert [row.id for row in released] == [case.id]
    claimed = repo.claim_for_invoice(
        invoice_id="next-run",
        invoice_number="RE-260021",
        sevdesk_contact_id="contact-1",
    )
    assert [row.id for row in claimed] == [case.id]


def test_stable_id_conflict_does_not_fall_back_to_matching_email() -> None:
    repo = _repo()
    _waiting_case(repo)

    claimed = repo.claim_for_invoice(
        invoice_id="target-conflict",
        invoice_number="RE-260012",
        sevdesk_contact_id="different-contact",
        customer_email="kunde@example.test",
    )

    assert claimed == []


def test_historic_invoice_is_not_treated_as_next_order() -> None:
    repo = _repo()
    _waiting_case(repo)
    yesterday = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).date()

    claimed = repo.claim_for_invoice(
        invoice_id="historic-target",
        invoice_number="RE-250001",
        invoice_date=yesterday.isoformat(),
        sevdesk_contact_id="contact-1",
    )

    assert claimed == []


def test_resolved_redelivery_does_not_prevent_a_later_case_for_same_invoice() -> None:
    repo = _repo()
    first = _waiting_case(repo)
    repo.mark_resolved(first.id)

    second = repo.create_invoice_case(
        invoice_id=first.source_invoice_id,
        invoice_number=first.source_invoice_number,
        sevdesk_contact_id="contact-1",
        items=[
            CustomerAftercareItemInput(
                role="MISSING_TO_SEND", sku="XW-2", name="Neue Nachlieferung", quantity=1
            )
        ],
    )

    assert second.state == "created"
    assert second.case.id != first.id
