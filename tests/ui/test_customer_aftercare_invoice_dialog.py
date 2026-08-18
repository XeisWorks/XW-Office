from __future__ import annotations

import uuid

from xw_office.core.config import AppConfig
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.services.crm.types import ContactRecord
from xw_office.services.customer_aftercare.invoice_service import (
    CustomerAftercareInvoiceService,
    InvoiceCreationResult,
)
from xw_office.services.customer_aftercare.service import CustomerAftercareService
from xw_office.services.sevdesk.contact_client import ContactClient
from xw_office.ui.modules.rechnungen.customer_aftercare_invoice_dialog import (
    CustomerAftercareInvoiceDialog,
)


def _case() -> CustomerAftercareCase:
    case = CustomerAftercareCase(
        case_type="B2B_WRONG_DELIVERY",
        customer_name="Musikhaus Mueller",
        customer_email="mueller@example.com",
        source_wix_order_number="21842",
        courtesy=True,
    )
    case.id = uuid.uuid4()  # type: ignore[assignment]
    return case


def _items() -> list[CustomerAftercareItem]:
    return [CustomerAftercareItem(role="WRONG_DELIVERED", name="Notenheft A", sku="XW-1", quantity=2)]


class _FakeContactClient:
    def __init__(self, contacts: list[ContactRecord]) -> None:
        self._contacts = contacts

    def list_contacts(self, **kwargs: object) -> list[ContactRecord]:
        return self._contacts


class _FakeAftercareService:
    def __init__(self) -> None:
        self.skip_calls: list[uuid.UUID] = []

    def mark_invoice_skipped(self, case_id: uuid.UUID) -> None:
        self.skip_calls.append(case_id)


class _FakeInvoiceService:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.raise_error: Exception | None = None

    def create_invoice(self, case, items, *, contact_id: str, country_code: str) -> InvoiceCreationResult:
        if self.raise_error is not None:
            raise self.raise_error
        self.create_calls.append({"contact_id": contact_id, "country_code": country_code})
        return InvoiceCreationResult(invoice_id="999", invoice_number="RE-999", reused_existing=False)


class _FakeContainer:
    def __init__(self, aftercare: _FakeAftercareService, invoices: _FakeInvoiceService, contacts: _FakeContactClient) -> None:
        self.config = AppConfig()
        self._aftercare = aftercare
        self._invoices = invoices
        self._contacts = contacts

    def resolve(self, typ: object) -> object:
        if typ is CustomerAftercareService:
            return self._aftercare
        if typ is CustomerAftercareInvoiceService:
            return self._invoices
        if typ is ContactClient:
            return self._contacts
        raise KeyError(str(typ))


def _wait_contacts_loaded(qtbot: object, dialog: CustomerAftercareInvoiceDialog) -> None:
    qtbot.waitUntil(lambda: dialog._contact_combo.count() > 0, timeout=3000)  # noqa: SLF001


def test_dialog_preselects_contact_matching_customer_email(qtbot: object) -> None:
    contacts = [
        ContactRecord(id="1", name="Andere Firma", email="andere@example.com"),
        ContactRecord(id="2", name="Musikhaus Mueller", email="mueller@example.com"),
    ]
    dialog = CustomerAftercareInvoiceDialog(
        _FakeContainer(_FakeAftercareService(), _FakeInvoiceService(), _FakeContactClient(contacts)),  # type: ignore[arg-type]
        _case(),
        _items(),
    )
    qtbot.addWidget(dialog)
    _wait_contacts_loaded(qtbot, dialog)

    assert dialog._contact_combo.currentData() == "2"  # noqa: SLF001


def test_positions_preview_shows_courtesy_discount(qtbot: object) -> None:
    dialog = CustomerAftercareInvoiceDialog(
        _FakeContainer(_FakeAftercareService(), _FakeInvoiceService(), _FakeContactClient([])),  # type: ignore[arg-type]
        _case(),
        _items(),
    )
    qtbot.addWidget(dialog)

    assert "Notenheft A" in dialog._positions_view.toPlainText()  # noqa: SLF001


def test_create_without_contact_shows_warning_and_does_not_call_service(
    qtbot: object, monkeypatch
) -> None:
    invoices = _FakeInvoiceService()
    dialog = CustomerAftercareInvoiceDialog(
        _FakeContainer(_FakeAftercareService(), invoices, _FakeContactClient([])),  # type: ignore[arg-type]
        _case(),
        _items(),
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.customer_aftercare_invoice_dialog.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )

    dialog._btn_create.click()  # noqa: SLF001

    assert invoices.create_calls == []


def test_create_with_contact_calls_invoice_service_and_accepts(qtbot: object) -> None:
    contacts = [ContactRecord(id="7", name="Musikhaus Mueller", email="mueller@example.com")]
    invoices = _FakeInvoiceService()
    dialog = CustomerAftercareInvoiceDialog(
        _FakeContainer(_FakeAftercareService(), invoices, _FakeContactClient(contacts)),  # type: ignore[arg-type]
        _case(),
        _items(),
    )
    qtbot.addWidget(dialog)
    _wait_contacts_loaded(qtbot, dialog)

    dialog._country_edit.setText("DE")  # noqa: SLF001
    dialog._btn_create.click()  # noqa: SLF001

    qtbot.waitUntil(lambda: len(invoices.create_calls) == 1, timeout=3000)
    assert invoices.create_calls[0] == {"contact_id": "7", "country_code": "DE"}
    qtbot.waitUntil(lambda: dialog.action_taken == "invoiced", timeout=3000)
    assert dialog.created_invoice is not None
    assert dialog.created_invoice.invoice_id == "999"


def test_skip_calls_mark_invoice_skipped_and_accepts(qtbot: object) -> None:
    aftercare = _FakeAftercareService()
    dialog = CustomerAftercareInvoiceDialog(
        _FakeContainer(aftercare, _FakeInvoiceService(), _FakeContactClient([])),  # type: ignore[arg-type]
        _case(),
        _items(),
    )
    qtbot.addWidget(dialog)

    dialog._btn_skip.click()  # noqa: SLF001

    qtbot.waitUntil(lambda: len(aftercare.skip_calls) == 1, timeout=3000)
    qtbot.waitUntil(lambda: dialog.action_taken == "skipped", timeout=3000)
