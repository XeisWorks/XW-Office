"""End-to-end test for invoice printing + mail flow parity."""
from __future__ import annotations

import json
from unittest.mock import patch

from xw_studio.core.config import AppConfig
from xw_studio.services.invoice_processing.service import (
    FulfillmentFlags,
    InvoiceProcessingService,
)
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary


class _InvoiceClientE2E:
    def __init__(self) -> None:
        self.render_calls: list[str] = []
        self.send_calls: list[tuple[str, str, bool]] = []
        self.mail_calls: list[dict[str, object]] = []
        self.fail_mail = False

    def list_invoice_summaries(self, *, limit: int, offset: int, status: int | None = None):
        if offset > 0 or status != 100:
            return []
        return [
            InvoiceSummary(
                id="INV-001",
                invoice_number="R-001",
                contact_name="John Doe",
                address_country_code="AT",
            )
        ]

    def render_invoice_pdf(self, invoice_id: str) -> None:
        self.render_calls.append(invoice_id)

    def get_invoice_pdf(self, invoice_id: str) -> bytes:
        return b"%PDF-1.4\ntest pdf content"

    def fetch_invoice_by_id(self, invoice_id: str) -> dict:
        return {
            "id": invoice_id,
            "invoiceNumber": "R-001",
            "name": "John Doe",
            "street": "Main St 1",
            "zip": "6020",
            "city": "Innsbruck",
            "addressCountryCode": "AT",
            "contact": {
                "name": "John Doe",
                "emails": [{"value": "john@example.test"}],
            },
        }

    def send_invoice_document(self, invoice_id: str, *, send_type: str, send_draft: bool) -> None:
        self.send_calls.append((invoice_id, send_type, send_draft))

    def send_invoice_via_email(
        self,
        invoice_id: str,
        *,
        to_email: str,
        subject: str,
        text: str,
        copy: bool = True,
    ) -> None:
        if self.fail_mail:
            raise RuntimeError("sevDesk mail down")
        self.mail_calls.append(
            {
                "invoice_id": invoice_id,
                "to_email": to_email,
                "subject": subject,
                "text": text,
                "copy": copy,
            }
        )


class _WixOrdersDigitalOnlyStub:
    def has_credentials(self) -> bool:
        return True

    def resolve_order_address_lines(self, reference: str) -> list[str]:
        return []

    def resolve_order_summary(self, reference: str) -> dict[str, str]:
        return {
            "wix_customer_email": "digital@example.test",
            "wix_customer_name": "John Doe",
        }

    def is_reference_digital_only(self, reference: str) -> bool:
        return True

    def list_fulfillments(self, reference: str) -> list[dict]:
        return []

    def get_fulfillable_items(self, reference: str) -> list[dict]:
        return []

    def fulfillment_status(self, reference: str) -> str:
        return "FULFILLED"


class _WixOrdersPhysicalStub:
    def has_credentials(self) -> bool:
        return True

    def resolve_order_address_lines(self, reference: str) -> list[str]:
        return ["John Doe", "Main St 1", "6020 Innsbruck", "AT"]

    def resolve_order_summary(self, reference: str) -> dict[str, str]:
        return {
            "wix_customer_email": "john@example.test",
            "wix_customer_name": "John Doe",
        }

    def is_reference_digital_only(self, reference: str) -> bool:
        return False

    def get_fulfillable_items(self, reference: str) -> list[dict]:
        return [{"id": "line-1"}]

    def create_fulfillment(self, reference: str, items: list[dict]) -> dict:
        return {"id": "ful-1"}

    def list_fulfillments(self, reference: str) -> list[dict]:
        return []

    def fulfillment_status(self, reference: str) -> str:
        return "NOT_FULFILLED"


class _SettingsRepoE2E:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self.values[key] = value_json


class _MailServiceStub:
    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.calls: list[dict[str, object]] = []

    def is_configured(self) -> bool:
        return self.configured

    @staticmethod
    def plain_text_to_html(value: str) -> str:
        return "<p>" + value.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"

    def send_mail(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str = "",
        attachments: list[object] | None = None,
    ) -> None:
        self.calls.append(
            {
                "to_email": to_email,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
                "attachments": list(attachments or []),
            }
        )


def test_invoice_print_step_uses_legacy_printer() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    service = InvoiceProcessingService(config, invoice_client, repo, None, mailer)

    with patch("xw_studio.services.printing.invoice_printer.print_pdf_file_silent") as mock_print, patch(
        "xw_studio.services.printing.invoice_printer.InvoicePrinter._printer_name"
    ) as mock_printer_name:
        mock_printer_name.return_value = "TestPrinter"
        summary = InvoiceSummary(id="INV-001", invoice_number="R-001", contact_name="John Doe")
        result = service._run_invoice_print_step(summary, FulfillmentFlags(invoice_printed=False))  # noqa: SLF001

    assert result.invoice_printed is True
    assert result.last_error == ""
    assert invoice_client.render_calls == ["INV-001"]
    assert mock_print.called


def test_label_print_step_uses_shipping_address_fallback() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    service = InvoiceProcessingService(config, invoice_client, repo, None, mailer)

    summary = InvoiceSummary(
        id="INV-001",
        invoice_number="R-001",
        contact_name="John Doe",
        display_country="AT",
    )
    full_invoice = {
        "id": "INV-001",
        "name": "John Doe",
        "street": "Billing St 1",
        "zip": "1010",
        "city": "Wien",
        "addressCountryCode": "AT",
        "deliveryName": "Jane Doe",
        "deliveryStreet": "Delivery St 5",
        "deliveryZip": "6020",
        "deliveryCity": "Innsbruck",
        "deliveryAddressCountry": "AT",
    }

    lines = service._shipping_lines_from_invoice(full_invoice, summary)  # noqa: SLF001

    assert "Jane Doe" in lines
    assert "Delivery St 5" in lines
    assert any("6020" in line for line in lines)


def test_label_print_step_falls_back_to_billing_when_no_delivery() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    service = InvoiceProcessingService(config, invoice_client, repo, None, mailer)

    summary = InvoiceSummary(
        id="INV-002",
        invoice_number="R-002",
        contact_name="Fallback Name",
        display_country="DE",
    )
    full_invoice = {
        "id": "INV-002",
        "name": "John Doe",
        "street": "Main St 1",
        "zip": "1010",
        "city": "Wien",
        "addressCountryCode": "AT",
    }

    lines = service._shipping_lines_from_invoice(full_invoice, summary)  # noqa: SLF001

    assert "John Doe" in lines
    assert "Main St 1" in lines
    assert any("1010" in line for line in lines)


def test_fullflow_invoice_and_label_steps() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    wix_orders = _WixOrdersPhysicalStub()
    service = InvoiceProcessingService(config, invoice_client, repo, wix_orders, mailer)
    invoice_client.list_invoice_summaries = lambda **_: [
        InvoiceSummary(
            id="INV-001",
            invoice_number="R-001",
            contact_name="John Doe",
            order_reference="WIX-INV-001",
            address_country_code="AT",
        )
    ]

    with patch("xw_studio.services.printing.invoice_printer.print_pdf_file_silent") as mock_inv_print, patch(
        "xw_studio.services.printing.label_printer.LabelPrinter.print_address"
    ) as mock_label_print, patch(
        "xw_studio.services.printing.invoice_printer.InvoicePrinter._printer_name"
    ) as mock_printer_name, patch(
        "xw_studio.services.printing.label_printer.LabelPrinter._printer_name"
    ) as mock_label_printer_name:
        mock_printer_name.return_value = "TestPrinter"
        mock_label_printer_name.return_value = "TestLabelPrinter"
        result = service.run_start_fullflow(full_mode=True)

    assert result["processed"] == 1
    assert result["failures"] == 0
    assert result["successful"] == 1
    assert mock_inv_print.called
    assert mock_label_print.called
    assert invoice_client.send_calls == [("INV-001", "VPR", False)]
    assert len(invoice_client.mail_calls) == 1
    assert invoice_client.mail_calls[0]["to_email"] == "john@example.test"
    assert len(mailer.calls) == 0


def test_fullflow_skips_print_for_digital_only_wix_orders() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    wix_orders = _WixOrdersDigitalOnlyStub()
    service = InvoiceProcessingService(config, invoice_client, repo, wix_orders, mailer)

    invoice_client.list_invoice_summaries = lambda **_: [
        InvoiceSummary(
            id="INV-DIGI-001",
            invoice_number="R-DIGI-001",
            contact_name="John Doe",
            order_reference="WIX-12345",
        )
    ]

    with patch("xw_studio.services.printing.invoice_printer.print_pdf_file_silent") as mock_inv_print, patch(
        "xw_studio.services.printing.label_printer.LabelPrinter.print_address"
    ) as mock_label_print:
        result = service.run_start_fullflow(full_mode=True)

    assert result["processed"] == 1
    assert result["failures"] == 0
    assert result["successful"] == 1
    assert invoice_client.send_calls == []
    assert invoice_client.mail_calls[0]["invoice_id"] == "INV-DIGI-001"
    assert invoice_client.mail_calls[0]["to_email"] == "digital@example.test"
    assert len(mailer.calls) == 0
    stored = json.loads(repo.values["rechnungen.fulfillment_status"])
    assert stored["INV-DIGI-001"]["mail_sent"] is True
    assert not mock_inv_print.called
    assert not mock_label_print.called


def test_start_fullflow_honors_abort_between_invoices() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    service = InvoiceProcessingService(config, invoice_client, repo, None, mailer)

    invoice_client.list_invoice_summaries = lambda **kwargs: (
        [
            InvoiceSummary(id="INV-001", invoice_number="R-001", contact_name="John Doe"),
            InvoiceSummary(id="INV-002", invoice_number="R-002", contact_name="Jane Doe"),
        ]
        if kwargs.get("offset", 0) == 0 and kwargs.get("status") == 100
        else []
    )

    state = {"checks": 0}

    def should_abort() -> bool:
        state["checks"] += 1
        return state["checks"] > 1

    result = service.run_start_fullflow(full_mode=False, should_abort=should_abort)

    assert result["processed"] == 1
    assert result["successful"] == 1
    assert result["failures"] == 0
    assert result["aborted"] is True
    assert invoice_client.send_calls == []
    assert invoice_client.mail_calls[0]["invoice_id"] == "INV-001"
    assert len(mailer.calls) == 0


def test_mail_only_fullflow_uses_sevdesk_email_when_no_print_copy_exists() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    service = InvoiceProcessingService(config, invoice_client, repo, None, mailer)

    invoice_client.list_invoice_summaries = lambda **_: [
        InvoiceSummary(
            id="INV-ORDER-001",
            invoice_number="R-ORDER-001",
            contact_name="John Doe",
            order_reference="20519",
        )
    ]

    result = service.run_start_fullflow(full_mode=False)

    assert result["processed"] == 1
    assert result["failures"] == 0
    assert invoice_client.send_calls == []
    assert invoice_client.mail_calls[0]["invoice_id"] == "INV-ORDER-001"
    assert invoice_client.mail_calls[0]["to_email"] == "john@example.test"
    assert len(mailer.calls) == 0
    stored = json.loads(repo.values["rechnungen.fulfillment_status"])
    assert stored["INV-ORDER-001"]["mail_sent"] is True


def test_mail_step_uses_graph_only_when_sevdesk_mail_fails() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    invoice_client.fail_mail = True
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    service = InvoiceProcessingService(config, invoice_client, repo, None, mailer)

    summary = InvoiceSummary(id="INV-001", invoice_number="R-001", contact_name="John Doe")
    result = service._run_mail_step(summary, FulfillmentFlags())  # noqa: SLF001

    assert result.mail_sent is True
    assert invoice_client.mail_calls == []
    assert len(mailer.calls) == 1
    assert mailer.calls[0]["to_email"] == "john@example.test"
    assert len(mailer.calls[0]["attachments"]) == 1


def test_print_label_for_invoice_uses_override_lines_and_persists_flag() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    service = InvoiceProcessingService(config, invoice_client, repo, None, mailer)

    with patch("xw_studio.services.printing.label_printer.LabelPrinter.print_address") as mock_label_print:
        result = service.print_label_for_invoice(
            "INV-001",
            override_lines=["John Doe", "Edited Street 9", "6020 Innsbruck", "AT"],
        )

    mock_label_print.assert_called_once_with(["John Doe", "Edited Street 9", "6020 Innsbruck", "AT"])
    assert result.label_printed is True
    stored = repo.get_value_json("rechnungen.fulfillment_status") or ""
    assert "label_printed" in stored


def test_fulfillment_flags_persist_across_batch() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    mailer = _MailServiceStub()
    service = InvoiceProcessingService(config, invoice_client, repo, None, mailer)

    flags = FulfillmentFlags(invoice_printed=True, last_run_iso="2026-04-04T09:00:00")
    service.write_fulfillment_flags("123", flags)

    loaded = service.read_fulfillment_flags("123")

    assert loaded.invoice_printed is True
    assert loaded.last_run_iso == "2026-04-04T09:00:00"
    stored = json.loads(repo.values["rechnungen.fulfillment_status"])
    assert stored["123"]["invoice_printed"] is True
