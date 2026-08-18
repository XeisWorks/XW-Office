"""Tests for CustomerAftercareInvoiceService (spec §8/§14 — idempotent, correctly-taxed invoicing)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.config import CustomerAftercareSection
from xw_office.models.base import Base
from xw_office.repositories.customer_aftercare import (
    CustomerAftercareItemInput,
    CustomerAftercareRepository,
)
from xw_office.services.customer_aftercare.invoice_service import (
    CustomerAftercareInvoiceService,
    build_marker,
)
from xw_office.services.customer_aftercare.pricing_policy import CustomerAftercarePricingPolicy
from xw_office.services.sevdesk.invoice_client import InvoiceSummary
from xw_office.services.sevdesk.tax_policy import CustomerAftercareTaxPolicy, load_tax_set_mapping
from xw_office.services.sevdesk.tax_set_client import SevdeskTaxSet


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class _FakeInvoiceClient:
    def __init__(self, *, search_results: list[InvoiceSummary] | None = None) -> None:
        self.search_results = search_results or []
        self.save_calls: list[dict[str, Any]] = []
        self.save_response: dict[str, Any] = {"invoice": {"id": "999", "invoiceNumber": "RE-999"}}
        self.raise_on_save: Exception | None = None

    def search_invoice_summaries(self, query: str, **kwargs: Any) -> tuple[list[InvoiceSummary], int]:
        return self.search_results, 100

    def update_invoice_draft(self, invoice: dict[str, Any], positions: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        if self.raise_on_save is not None:
            raise self.raise_on_save
        self.save_calls.append({"invoice": invoice, "positions": positions})
        return self.save_response


class _FakeTaxSetClient:
    def __init__(self, texts_to_ids: dict[str, str]) -> None:
        self._map = texts_to_ids

    def find_by_text(self, text: str, **kwargs: Any) -> SevdeskTaxSet | None:
        tax_set_id = self._map.get(text)
        return SevdeskTaxSet(id=tax_set_id, object_name="TaxSet", text=text) if tax_set_id else None


class _FakeCatalog:
    def resolve_sku(self, sku: str) -> None:
        return None


def _service(
    session_factory: sessionmaker[Session],
    *,
    invoice_client: _FakeInvoiceClient | None = None,
    tax_ids: dict[str, str] | None = None,
) -> tuple[CustomerAftercareInvoiceService, CustomerAftercareRepository, _FakeInvoiceClient]:
    repo = CustomerAftercareRepository(session_factory)
    client = invoice_client or _FakeInvoiceClient()
    tax_set_client = _FakeTaxSetClient(
        tax_ids if tax_ids is not None else {"Deutsche MwSt. 7%": "tax-de-7"}
    )
    service = CustomerAftercareInvoiceService(
        repo,
        client,  # type: ignore[arg-type]
        tax_set_client,  # type: ignore[arg-type]
        _FakeCatalog(),  # type: ignore[arg-type]
        CustomerAftercarePricingPolicy(CustomerAftercareSection()),
        CustomerAftercareTaxPolicy(load_tax_set_mapping()),
    )
    return service, repo, client


def _case_with_items(repo: CustomerAftercareRepository, *, courtesy: bool = True, customer_type: str = "B2B"):
    reservation = repo.reserve_case_by_message_id(source_message_id="msg-1", source_wix_order_number="21842")
    repo.confirm_classification(
        reservation.case.id,
        case_type="B2B_WRONG_DELIVERY",
        courtesy=courtesy,
        customer_type=customer_type,
        wait_for_next_order=False,
        due_at=None,
        trigger_now=True,
    )
    repo.add_items(
        reservation.case.id,
        [
            CustomerAftercareItemInput(
                role="WRONG_DELIVERED",
                sku="XW-1",
                name="Notenheft A",
                quantity=2,
                source_unit_price=Decimal("10.00"),
                source_tax_rate=Decimal("7.00"),
            )
        ],
    )
    case = repo.get_case(reservation.case.id)
    items = repo.get_items(reservation.case.id)
    return case, items


def test_create_invoice_builds_custom_tax_set_and_courtesy_discount(session_factory: sessionmaker[Session]) -> None:
    # DE/b2c maps to a specific TaxSet ("Deutsche MwSt. 7%") in the verbatim-copied
    # table; DE/b2b is NOT in the table and would resolve to "eu" instead (see
    # test_customer_aftercare_tax_policy.py) — b2c is used here to exercise the
    # "custom" TaxSet branch end-to-end.
    service, repo, client = _service(session_factory)
    case, items = _case_with_items(repo, courtesy=True, customer_type="B2C")

    result = service.create_invoice(case, items, contact_id="contact-1", country_code="DE")

    assert result.invoice_id == "999"
    assert result.reused_existing is False
    assert len(client.save_calls) == 1
    invoice_payload = client.save_calls[0]["invoice"]
    assert invoice_payload["taxType"] == "custom"
    assert invoice_payload["taxSet"] == {"id": "tax-de-7", "objectName": "TaxSet"}
    assert build_marker(case.id) in invoice_payload["customerInternalNote"]
    assert "WIX:21842" in invoice_payload["customerInternalNote"]

    positions = client.save_calls[0]["positions"]
    assert positions[0]["discount"] == 30.0
    assert positions[0]["isPercentage"] is True
    assert positions[0]["taxRate"] == 7.0

    updated_case = repo.get_case(case.id)
    assert updated_case.invoice_status == "created"
    assert updated_case.sevdesk_invoice_id == "999"


def test_create_invoice_reuses_existing_invoice_by_marker_idemp_02(session_factory: sessionmaker[Session]) -> None:
    case_uuid_holder: dict[str, Any] = {}

    def make_summary(case_id: Any) -> InvoiceSummary:
        return InvoiceSummary.model_validate(
            {"id": "500", "invoiceNumber": "RE-500", "sevdesk_reference": build_marker(case_id)}
        )

    repo_probe = CustomerAftercareRepository(session_factory)
    case, items = _case_with_items(repo_probe)
    case_uuid_holder["id"] = case.id

    client = _FakeInvoiceClient(search_results=[make_summary(case.id)])
    service, repo, client = _service(session_factory, invoice_client=client)

    result = service.create_invoice(case, items, contact_id="contact-1", country_code="DE")

    assert result.reused_existing is True
    assert result.invoice_id == "500"
    assert client.save_calls == []  # no duplicate create call
    assert repo.get_case(case.id).sevdesk_invoice_id == "500"


def test_create_invoice_raises_when_tax_rate_missing(session_factory: sessionmaker[Session]) -> None:
    service, repo, client = _service(session_factory)
    reservation = repo.reserve_case_by_message_id(source_message_id="msg-2")
    repo.confirm_classification(
        reservation.case.id,
        case_type="B2C_WRONG_DELIVERY",
        courtesy=True,
        customer_type="B2C",
        wait_for_next_order=False,
        due_at=None,
        trigger_now=True,
    )
    repo.add_items(
        reservation.case.id,
        [CustomerAftercareItemInput(role="WRONG_DELIVERED", name="Ohne Steuersatz", quantity=1)],
    )
    case = repo.get_case(reservation.case.id)
    items = repo.get_items(reservation.case.id)

    with pytest.raises(RuntimeError, match="Steuersatz fehlt"):
        service.create_invoice(case, items, contact_id="contact-1", country_code="AT")
    assert client.save_calls == []


def test_create_invoice_raises_when_no_invoiceable_items(session_factory: sessionmaker[Session]) -> None:
    service, repo, client = _service(session_factory)
    reservation = repo.reserve_case_by_message_id(source_message_id="msg-3")
    repo.confirm_classification(
        reservation.case.id,
        case_type="B2B_MISSING_ITEMS",
        courtesy=True,
        customer_type="B2B",
        wait_for_next_order=False,
        due_at=None,
        trigger_now=True,
    )
    repo.add_items(
        reservation.case.id,
        [CustomerAftercareItemInput(role="MISSING_TO_SEND", name="Nachzusenden", quantity=1)],
    )
    case = repo.get_case(reservation.case.id)
    items = repo.get_items(reservation.case.id)

    with pytest.raises(RuntimeError, match="Kein verrechenbarer Artikel"):
        service.create_invoice(case, items, contact_id="contact-1", country_code="AT")


def test_create_invoice_raises_when_tax_set_not_configured_in_sevdesk(session_factory: sessionmaker[Session]) -> None:
    service, repo, client = _service(session_factory, tax_ids={})  # no TaxSets configured
    case, items = _case_with_items(repo, customer_type="B2C")  # DE/b2c -> "custom" branch

    with pytest.raises(RuntimeError, match="ist im sevDesk-Konto nicht konfiguriert"):
        service.create_invoice(case, items, contact_id="contact-1", country_code="DE")
    assert client.save_calls == []


def test_create_invoice_marks_failed_on_sevdesk_error_and_reraises(session_factory: sessionmaker[Session]) -> None:
    client = _FakeInvoiceClient()
    client.raise_on_save = RuntimeError("sevDesk timeout")
    service, repo, client = _service(session_factory, invoice_client=client)
    case, items = _case_with_items(repo)

    with pytest.raises(RuntimeError, match="sevDesk timeout"):
        service.create_invoice(case, items, contact_id="contact-1", country_code="DE")

    updated_case = repo.get_case(case.id)
    assert updated_case.invoice_status == "failed"
    assert "sevDesk timeout" in updated_case.invoice_error


def test_preserves_zero_percent_tax_rate_testmatrix_9(session_factory: sessionmaker[Session]) -> None:
    service, repo, client = _service(session_factory)
    reservation = repo.reserve_case_by_message_id(source_message_id="msg-4")
    repo.confirm_classification(
        reservation.case.id,
        case_type="B2B_CUSTOMER_ORDER_ERROR",
        courtesy=False,
        customer_type="B2B",
        wait_for_next_order=False,
        due_at=None,
        trigger_now=True,
    )
    repo.add_items(
        reservation.case.id,
        [
            CustomerAftercareItemInput(
                role="CORRECTED_ORDER_ITEM",
                name="Export-Artikel",
                quantity=1,
                source_unit_price=Decimal("50.00"),
                source_tax_rate=Decimal("0.00"),
            )
        ],
    )
    case = repo.get_case(reservation.case.id)
    items = repo.get_items(reservation.case.id)

    # AT is intentionally absent from the tax-set mapping for both b2b/b2c
    # (spec §10) -> falls to sevDesk's domestic default, no TaxSet lookup needed.
    service.create_invoice(case, items, contact_id="contact-1", country_code="AT")

    positions = client.save_calls[0]["positions"]
    assert positions[0]["taxRate"] == 0.0
    invoice_payload = client.save_calls[0]["invoice"]
    assert invoice_payload["taxType"] == "default"
