"""Tests for CustomerAftercareTriggerService (spec §5/§6 — 20-day / new-order trigger)."""
from __future__ import annotations

import datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.customer_aftercare import CustomerAftercareRepository
from xw_office.services.customer_aftercare.trigger_service import CustomerAftercareTriggerService


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class _FakeWixOrders:
    def __init__(self, orders_by_key: dict[str, list[dict[str, Any]]]) -> None:
        self._orders_by_key = orders_by_key
        self.calls: list[dict[str, Any]] = []

    def find_recent_orders_by_contact_or_email(
        self,
        *,
        contact_id: str = "",
        email: str = "",
        since: datetime.datetime | None = None,
        exclude_order_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self.calls.append({"contact_id": contact_id, "email": email, "exclude_order_id": exclude_order_id})
        key = contact_id or email
        return self._orders_by_key.get(key, [])


def _waiting_case(repo: CustomerAftercareRepository, *, message_id: str, email: str = "", contact_id: str = "", due_at):
    reservation = repo.reserve_case_by_message_id(
        source_message_id=message_id, customer_email=email, wix_contact_id=contact_id
    )
    repo.confirm_classification(
        reservation.case.id,
        case_type="B2B_WRONG_DELIVERY",
        courtesy=True,
        customer_type="B2B",
        wait_for_next_order=True,
        due_at=due_at,
        trigger_now=False,
    )
    return reservation.case


def test_check_new_orders_triggers_waiting_case_on_new_order(session_factory: sessionmaker[Session]) -> None:
    repo = CustomerAftercareRepository(session_factory)
    now = datetime.datetime.now(datetime.timezone.utc)
    case = _waiting_case(repo, message_id="m-1", email="mueller@example.com", due_at=now + datetime.timedelta(days=20))

    wix = _FakeWixOrders({"mueller@example.com": [{"id": "order-2", "number": "21900"}]})
    trigger = CustomerAftercareTriggerService(repo, wix)  # type: ignore[arg-type]

    result = trigger.check_new_orders_for_waiting_cases()

    assert result.checked == 1
    assert result.triggered == 1
    updated = repo.get_case(case.id)
    assert updated.status == "TRIGGERED"
    assert updated.trigger_reason == "NEW_ORDER"
    assert updated.trigger_wix_order_number == "21900"


def test_check_due_cases_triggers_after_20_days(session_factory: sessionmaker[Session]) -> None:
    repo = CustomerAftercareRepository(session_factory)
    now = datetime.datetime.now(datetime.timezone.utc)
    case = _waiting_case(repo, message_id="m-2", email="mueller@example.com", due_at=now - datetime.timedelta(days=1))

    trigger = CustomerAftercareTriggerService(repo, None)

    result = trigger.check_due_cases(now=now)

    assert result.triggered == 1
    updated = repo.get_case(case.id)
    assert updated.status == "TRIGGERED"
    assert updated.trigger_reason == "MAX_WAIT_EXPIRED"


def test_check_new_orders_skips_cases_without_contact_id_or_email(
    session_factory: sessionmaker[Session],
) -> None:
    """MATCH-01: a name alone must never auto-trigger."""
    repo = CustomerAftercareRepository(session_factory)
    now = datetime.datetime.now(datetime.timezone.utc)
    _waiting_case(repo, message_id="m-3", due_at=now + datetime.timedelta(days=20))

    wix = _FakeWixOrders({})
    trigger = CustomerAftercareTriggerService(repo, wix)  # type: ignore[arg-type]

    result = trigger.check_new_orders_for_waiting_cases()

    assert result.checked == 0
    assert result.triggered == 0
    assert wix.calls == []


def test_check_new_orders_can_trigger_multiple_cases_of_same_merchant(
    session_factory: sessionmaker[Session],
) -> None:
    """Testmatrix #18: several cases of the same merchant may all trigger off one new order."""
    repo = CustomerAftercareRepository(session_factory)
    now = datetime.datetime.now(datetime.timezone.utc)
    case_a = _waiting_case(repo, message_id="m-4a", email="mueller@example.com", due_at=now + datetime.timedelta(days=20))
    case_b = _waiting_case(repo, message_id="m-4b", email="mueller@example.com", due_at=now + datetime.timedelta(days=20))

    wix = _FakeWixOrders({"mueller@example.com": [{"id": "order-9", "number": "22000"}]})
    trigger = CustomerAftercareTriggerService(repo, wix)  # type: ignore[arg-type]

    result = trigger.check_new_orders_for_waiting_cases()

    assert result.triggered == 2
    assert repo.get_case(case_a.id).status == "TRIGGERED"
    assert repo.get_case(case_b.id).status == "TRIGGERED"


def test_check_new_orders_excludes_source_order_via_wix_client_param(
    session_factory: sessionmaker[Session],
) -> None:
    """Testmatrix #19: the source order itself must be excluded (delegated to the Wix client call)."""
    repo = CustomerAftercareRepository(session_factory)
    now = datetime.datetime.now(datetime.timezone.utc)
    reservation = repo.reserve_case_by_message_id(
        source_message_id="m-5",
        customer_email="mueller@example.com",
        source_wix_order_id="source-order-id",
    )
    repo.confirm_classification(
        reservation.case.id,
        case_type="B2B_WRONG_DELIVERY",
        courtesy=True,
        customer_type="B2B",
        wait_for_next_order=True,
        due_at=now + datetime.timedelta(days=20),
        trigger_now=False,
    )

    wix = _FakeWixOrders({"mueller@example.com": []})
    trigger = CustomerAftercareTriggerService(repo, wix)  # type: ignore[arg-type]

    trigger.check_new_orders_for_waiting_cases()

    assert wix.calls[0]["exclude_order_id"] == "source-order-id"
