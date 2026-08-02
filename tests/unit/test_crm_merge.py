"""Tests for CRM merge service behavior: fields, preflight, and loser policy."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from xw_office.core.config import AppConfig, CrmSection
from xw_office.services.crm.service import CrmService, MergeBlockedError
from xw_office.services.crm.types import ContactRecord
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


def _config(*, merge_loser_policy: str = "delete_if_empty") -> AppConfig:
    return AppConfig(crm=CrmSection(merge_loser_policy=merge_loser_policy))


def _invoice(*, status_code: int = 100) -> InvoiceSummary:
    return InvoiceSummary.from_api_object({"id": "1", "status": status_code})


@dataclass
class _ContactClientStub:
    update_calls: list[ContactRecord] = field(default_factory=list)
    delete_calls: list[str] = field(default_factory=list)
    archive_calls: list[tuple[str, str]] = field(default_factory=list)
    raise_on_delete: bool = False

    def update_contact_fields(self, record: ContactRecord) -> None:
        self.update_calls.append(record)

    def delete_contact(self, contact_id: str) -> None:
        if self.raise_on_delete:
            raise RuntimeError("sevDesk: Kontakt hat verknuepfte Belege")
        self.delete_calls.append(contact_id)

    def archive_contact(self, contact_id: str, *, current_name: str, name_prefix: str = "[MERGED] ") -> None:
        self.archive_calls.append((contact_id, current_name))


@dataclass
class _InvoiceClientStub:
    invoices_by_contact: dict[str, list[InvoiceSummary]] = field(default_factory=dict)

    def list_invoice_summaries_for_contact(self, contact_id: str, *, limit: int = 200) -> list[InvoiceSummary]:
        return self.invoices_by_contact.get(contact_id, [])


def test_merge_prefers_master_non_empty_fields() -> None:
    service = CrmService(_config(), contact_client=None)
    master = ContactRecord(
        id="100",
        name="XeisWorks GmbH",
        email="office@xeisworks.test",
        phone="+43-1-1000",
        city="Wien",
    )
    duplicate = ContactRecord(
        id="101",
        name="XeisWorks",
        email="other@xeisworks.test",
        phone="+43-1-2000",
        city="Graz",
    )

    result = service.merge_contacts(master, duplicate)

    assert result.master_id == "100"
    assert result.duplicate_id == "101"
    assert result.merged.name == "XeisWorks GmbH"
    assert result.merged.email == "office@xeisworks.test"
    assert result.merged.phone == "+43-1-1000"
    assert result.merged.city == "Wien"
    assert result.loser_outcome == "not_written"


def test_merge_fills_missing_master_fields_from_duplicate() -> None:
    service = CrmService(_config(), contact_client=None)
    master = ContactRecord(id="100", name="", email=None, phone="", city=None)
    duplicate = ContactRecord(
        id="101",
        name="Musikhaus Nord",
        email="kontakt@musikhaus.test",
        phone="+43-1-3000",
        city="Linz",
    )

    result = service.merge_contacts(master, duplicate)

    assert result.merged.id == "100"
    assert result.merged.name == "Musikhaus Nord"
    assert result.merged.email == "kontakt@musikhaus.test"
    assert result.merged.phone == "+43-1-3000"
    assert result.merged.city == "Linz"


def test_merge_without_invoice_client_writes_back_and_deletes() -> None:
    stub = _ContactClientStub()
    service = CrmService(_config(), contact_client=stub)  # type: ignore[arg-type]
    master = ContactRecord(id="200", name="Master", email=None, phone=None, city=None)
    duplicate = ContactRecord(id="201", name="Dup", email="dup@test", phone=None, city=None)

    result = service.merge_contacts(master, duplicate)

    assert result.master_id == "200"
    assert result.loser_outcome == "deleted"
    assert [r.id for r in stub.update_calls] == ["200"]
    assert stub.delete_calls == ["201"]
    assert stub.archive_calls == []


def test_merge_with_no_loser_invoices_deletes_the_duplicate() -> None:
    contacts = _ContactClientStub()
    invoices = _InvoiceClientStub(invoices_by_contact={"301": []})
    service = CrmService(_config(), contact_client=contacts, invoice_client=invoices)  # type: ignore[arg-type]
    master = ContactRecord(id="300", name="Master")
    duplicate = ContactRecord(id="301", name="Dup")

    result = service.merge_contacts(master, duplicate)

    assert result.loser_outcome == "deleted"
    assert contacts.delete_calls == ["301"]


def test_merge_with_blocked_invoices_raises_without_force() -> None:
    contacts = _ContactClientStub()
    invoices = _InvoiceClientStub(
        invoices_by_contact={"401": [_invoice(status_code=200)]}
    )
    service = CrmService(_config(), contact_client=contacts, invoice_client=invoices)  # type: ignore[arg-type]
    master = ContactRecord(id="400", name="Master")
    duplicate = ContactRecord(id="401", name="Dup")

    with pytest.raises(MergeBlockedError) as excinfo:
        service.merge_contacts(master, duplicate)

    assert excinfo.value.report.has_blocked_invoices is True
    # Nothing was written to sevDesk — the merge stopped before any call.
    assert contacts.update_calls == []
    assert contacts.delete_calls == []


def test_merge_with_blocked_invoices_and_force_archives_instead_of_deleting() -> None:
    contacts = _ContactClientStub()
    invoices = _InvoiceClientStub(
        invoices_by_contact={"501": [_invoice(status_code=200)]}
    )
    service = CrmService(_config(), contact_client=contacts, invoice_client=invoices)  # type: ignore[arg-type]
    master = ContactRecord(id="500", name="Master")
    duplicate = ContactRecord(id="501", name="Dup GmbH")

    result = service.merge_contacts(master, duplicate, force=True)

    assert result.loser_outcome == "archived"
    assert contacts.delete_calls == []
    assert contacts.archive_calls == [("501", "Dup GmbH")]


def test_preflight_merge_without_invoice_client_raises() -> None:
    service = CrmService(_config(), contact_client=None, invoice_client=None)
    with pytest.raises(RuntimeError):
        service.preflight_merge(ContactRecord(id="1", name="X"))


def test_merge_loser_policy_archive_always_never_deletes() -> None:
    contacts = _ContactClientStub()
    invoices = _InvoiceClientStub(invoices_by_contact={"601": []})
    service = CrmService(
        _config(merge_loser_policy="archive_always"),
        contact_client=contacts,  # type: ignore[arg-type]
        invoice_client=invoices,  # type: ignore[arg-type]
    )
    master = ContactRecord(id="600", name="Master")
    duplicate = ContactRecord(id="601", name="Dup")

    result = service.merge_contacts(master, duplicate)

    assert result.loser_outcome == "archived"
    assert contacts.delete_calls == []
    assert contacts.archive_calls == [("601", "Dup")]


def test_merge_loser_policy_ignore_only_writes_master_fields() -> None:
    contacts = _ContactClientStub()
    invoices = _InvoiceClientStub(invoices_by_contact={"701": []})
    service = CrmService(
        _config(merge_loser_policy="ignore"),
        contact_client=contacts,  # type: ignore[arg-type]
        invoice_client=invoices,  # type: ignore[arg-type]
    )
    master = ContactRecord(id="700", name="Master")
    duplicate = ContactRecord(id="701", name="Dup")

    result = service.merge_contacts(master, duplicate)

    assert result.loser_outcome == "ignored"
    assert contacts.delete_calls == []
    assert contacts.archive_calls == []
    assert len(contacts.update_calls) == 1


def test_merge_falls_back_to_archive_when_sevdesk_refuses_delete() -> None:
    contacts = _ContactClientStub(raise_on_delete=True)
    invoices = _InvoiceClientStub(invoices_by_contact={"801": []})
    service = CrmService(_config(), contact_client=contacts, invoice_client=invoices)  # type: ignore[arg-type]
    master = ContactRecord(id="800", name="Master")
    duplicate = ContactRecord(id="801", name="Dup GmbH")

    result = service.merge_contacts(master, duplicate)

    assert result.loser_outcome == "archived"
    assert contacts.archive_calls == [("801", "Dup GmbH")]
