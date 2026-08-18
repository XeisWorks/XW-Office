"""Tests for CustomerAftercareService.confirm_case (spec §2/§4) and manager-dialog filters."""
from __future__ import annotations

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.config import AppConfig
from xw_office.models.base import Base
from xw_office.repositories.customer_aftercare import CustomerAftercareRepository
from xw_office.services.customer_aftercare.inbox_service import CustomerAftercareInboxService
from xw_office.services.customer_aftercare.service import CustomerAftercareService


class _Secrets:
    def get_secret(self, key: str) -> str:
        return ""


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def service(session_factory: sessionmaker[Session]) -> CustomerAftercareService:
    repo = CustomerAftercareRepository(session_factory)
    inbox = CustomerAftercareInboxService(repo, _Secrets())
    return CustomerAftercareService(repo, inbox, AppConfig())


def _new_case(service: CustomerAftercareService, message_id: str):
    repo = service._repo  # noqa: SLF001 - test-only introspection
    assert repo is not None
    return repo.reserve_case_by_message_id(source_message_id=message_id).case


def test_confirm_case_b2b_wrong_delivery_waits_20_days(service: CustomerAftercareService) -> None:
    case = _new_case(service, "m-1")
    confirmed = service.confirm_case(case.id, case_type="B2B_WRONG_DELIVERY", courtesy=True)
    assert confirmed is not None
    assert confirmed.status == "WAITING"
    assert confirmed.customer_type == "B2B"
    assert confirmed.courtesy is True
    assert confirmed.due_at is not None
    delta = confirmed.due_at - datetime.datetime.now(datetime.timezone.utc)
    assert 19 <= delta.days <= 20


def test_confirm_case_b2c_wrong_delivery_triggers_immediately(service: CustomerAftercareService) -> None:
    case = _new_case(service, "m-2")
    confirmed = service.confirm_case(case.id, case_type="B2C_WRONG_DELIVERY", courtesy=True)
    assert confirmed is not None
    assert confirmed.status == "TRIGGERED"
    assert confirmed.due_at is None
    assert confirmed.invoice_required is False


def test_confirm_case_customer_order_error_triggers_and_requires_invoice(
    service: CustomerAftercareService,
) -> None:
    case = _new_case(service, "m-3")
    confirmed = service.confirm_case(case.id, case_type="B2B_CUSTOMER_ORDER_ERROR", courtesy=True)
    assert confirmed is not None
    assert confirmed.status == "TRIGGERED"
    assert confirmed.invoice_required is True


def test_confirm_case_unknown_never_auto_triggers(service: CustomerAftercareService) -> None:
    case = _new_case(service, "m-4")
    confirmed = service.confirm_case(case.id, case_type="UNKNOWN", courtesy=True)
    assert confirmed is not None
    assert confirmed.status == "WAITING"
    assert confirmed.due_at is None  # never picked up by the due-date trigger poll


def test_manager_dialog_filters_map_to_expected_statuses(service: CustomerAftercareService) -> None:
    pending = _new_case(service, "m-5")
    waiting_case = _new_case(service, "m-6")
    service.confirm_case(waiting_case.id, case_type="B2B_MISSING_ITEMS", courtesy=True)
    due_case = _new_case(service, "m-7")
    service.confirm_case(due_case.id, case_type="B2C_WRONG_DELIVERY", courtesy=True)

    assert [c.id for c in service.list_cases_for_filter("zu_pruefen")] == [pending.id]
    assert [c.id for c in service.list_cases_for_filter("wartet")] == [waiting_case.id]
    assert [c.id for c in service.list_cases_for_filter("faellig")] == [due_case.id]
    assert service.count_pending_review() == 1
    assert service.count_due() == 1
