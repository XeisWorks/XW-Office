"""Tests for invoice processing service post-processing rules."""
from __future__ import annotations

import json
from types import SimpleNamespace

from xw_studio.core.config import AppConfig
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary


class _InvoiceClientStub:
    def __init__(self, rows: list[InvoiceSummary]) -> None:
        self._rows = rows
        self.render_calls: list[str] = []
        self.invoice_payloads: dict[str, dict[str, object]] = {}
        self.mail_calls: list[dict[str, object]] = []
        self.fail_mail = False

    def list_invoice_summaries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: int | None = None,
    ) -> list[InvoiceSummary]:
        return list(self._rows)

    def fetch_invoice_by_id(self, invoice_id: str) -> dict[str, object]:
        if invoice_id in self.invoice_payloads:
            return dict(self.invoice_payloads[invoice_id])
        return {
            "id": invoice_id,
            "invoiceNumber": "RE-TEST-1",
            "name": "Max Mustermann",
            "contact": {"emails": [{"value": "max@example.test"}]},
        }

    def render_invoice_pdf(self, invoice_id: str) -> None:
        self.render_calls.append(invoice_id)

    def get_invoice_pdf(self, invoice_id: str) -> bytes:
        return b"%PDF-1.4\nstub"

    def send_invoice_document(self, invoice_id: str, *, send_type: str, send_draft: bool) -> None:
        self.last_send_document = {
            "invoice_id": invoice_id,
            "send_type": send_type,
            "send_draft": send_draft,
        }

    def send_invoice_via_email(
        self,
        invoice_id: str,
        *,
        to_email: str,
        subject: str,
        text: str,
        copy: bool = True,
    ) -> dict[str, object]:
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
        return {"ok": True}


class _RepoStub:
    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    def get_value_json(self, key: str) -> str | None:
        return self._data.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self._data[key] = value_json


class _WixOrdersStub:
    def __init__(self) -> None:
        self.calls = 0
        self._digital_only = False
        self._fulfillment_status = "NOT_FULFILLED"
        self._fulfillable_items: list[dict[str, str]] = []
        self._fulfillments: list[dict[str, str]] = []
        self.orders: dict[str, dict[str, object]] = {}
        self.line_items: dict[str, list[object]] = {}

    def has_credentials(self) -> bool:
        return True

    def resolve_order_address_lines(self, reference: str) -> list[str]:
        self.calls += 1
        if reference == "12345":
            return ["Wix Name", "Wix Strasse 1", "1010 Wien", "AT"]
        return []

    def list_fulfillments(self, reference: str) -> list[dict[str, str]]:
        return list(self._fulfillments)

    def resolve_order_summary(self, reference: str) -> dict[str, str]:
        return {
            "wix_customer_email": "wix@example.test",
            "wix_customer_name": "Wix Name",
        }

    def resolve_order(self, reference: str) -> dict[str, object]:
        return dict(self.orders.get(reference, {}))

    @staticmethod
    def shipping_address_lines_from_order(order: dict[str, object]) -> list[str]:
        value = order.get("shipping_lines")
        return list(value) if isinstance(value, list) else []

    @staticmethod
    def billing_address_lines_from_order(order: dict[str, object]) -> list[str]:
        value = order.get("billing_lines")
        return list(value) if isinstance(value, list) else []

    def is_reference_digital_only(self, reference: str) -> bool:
        return self._digital_only

    def get_fulfillable_items(self, reference: str) -> list[dict[str, str]]:
        return list(self._fulfillable_items)

    def create_fulfillment(self, reference: str, items: list[dict[str, str]]) -> dict[str, str]:
        return {"id": "fulfillment-1"} if items else {}

    def fulfillment_status(self, reference: str) -> str:
        return self._fulfillment_status

    def fetch_order_line_items(self, reference: str) -> list[object]:
        return list(self.line_items.get(reference, []))


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


class _DraftServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def repair_draft_product_mapping(
        self,
        invoice_id: str,
        wix_order_number: str,
        *,
        create_missing_products: bool = False,
    ) -> bool:
        self.calls.append((invoice_id, wix_order_number))
        return True


def test_sensitive_country_override_from_settings() -> None:
    rows = [
        InvoiceSummary(
            id="1",
            invoice_number="R-1",
            address_country_code="AT",
            delivery_country_code="KP",
            is_sensitive_country=False,
        )
    ]
    repo = _RepoStub({"rechnungen.sensitive_country_codes": json.dumps(["AT"])})
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(rows), repo)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert len(result) == 1
    assert result[0].is_sensitive_country is True


def test_sensitive_country_falls_back_to_default_list() -> None:
    rows = [
        InvoiceSummary(
            id="2",
            invoice_number="R-2",
            address_country_code="RU",
            is_sensitive_country=False,
        )
    ]
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(rows), None)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert result[0].is_sensitive_country is True


def test_unreleased_sku_flags_from_settings() -> None:
    rows = [
        InvoiceSummary(
            id="3",
            invoice_number="R-3",
            order_reference="WIX XW-6-003",
            has_unreleased_sku=False,
        )
    ]
    repo = _RepoStub(
        {
            "rechnungen.sku_flags": json.dumps(
                {
                    "exact": ["XW-123"],
                    "prefixes": ["XW-6"],
                }
            )
        }
    )
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(rows), repo)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert len(result) == 1
    assert result[0].has_unreleased_sku is True


def test_is_flagged_sku_uses_same_settings_as_hint_logic() -> None:
    repo = _RepoStub(
        {
            "rechnungen.sku_flags": json.dumps(
                {
                    "exact": ["XW-123"],
                    "prefixes": ["XW-6"],
                }
            )
        }
    )
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub([]), repo)  # type: ignore[arg-type]

    assert svc.is_flagged_sku("XW-6213") is True
    assert svc.is_flagged_sku("XW-123") is True
    assert svc.is_flagged_sku("XW-9999") is False


def test_unreleased_sku_flags_fall_back_to_defaults() -> None:
    rows = [
        InvoiceSummary(
            id="4",
            invoice_number="R-4",
            order_reference="XW-010",
            has_unreleased_sku=False,
        )
    ]
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(rows), None)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert result[0].has_unreleased_sku is True


def test_shipping_lines_prefer_wix_when_available() -> None:
    summary = InvoiceSummary(id="5", invoiceNumber="R-5", order_reference="12345")
    wix = _WixOrdersStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([summary]),  # type: ignore[arg-type]
        None,
        wix,  # type: ignore[arg-type]
    )

    lines = svc._shipping_lines_from_invoice({}, summary)  # noqa: SLF001

    assert lines == ["Wix Name", "Wix Strasse 1", "1010 Wien", "AT"]
    assert wix.calls == 1


def test_shipping_lines_use_wix_cache_for_same_reference() -> None:
    summary = InvoiceSummary(id="6", invoiceNumber="R-6", order_reference="12345")
    wix = _WixOrdersStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([summary]),  # type: ignore[arg-type]
        None,
        wix,  # type: ignore[arg-type]
    )

    first = svc._shipping_lines_from_invoice({}, summary)  # noqa: SLF001
    second = svc._shipping_lines_from_invoice({}, summary)  # noqa: SLF001

    assert first == second
    assert wix.calls == 1


def test_invoice_detail_context_uses_sevdesk_shipping_for_older_invoices() -> None:
    summary = InvoiceSummary(id="6a", invoiceNumber="RE-ALT-1", contact_name="Alt Kunde")
    client = _InvoiceClientStub([summary])
    client.invoice_payloads["6a"] = {
        "id": "6a",
        "invoiceNumber": "RE-ALT-1",
        "deliveryName": "Alt Kunde",
        "deliveryStreet": "Hauptstrasse 7",
        "deliveryZip": "8010",
        "deliveryCity": "Graz",
        "deliveryAddressCountry": "Austria",
        "contact": {"emails": [{"value": "alt@example.test"}]},
    }
    svc = InvoiceProcessingService(AppConfig(), client, None)  # type: ignore[arg-type]

    context = svc.get_invoice_detail_context(summary)

    assert context["customer_email"] == "alt@example.test"
    assert context["shipping_lines"] == ["Alt Kunde", "Hauptstrasse 7", "8010 Graz", "Austria"]


def test_mail_step_uses_saved_template_when_available() -> None:
    summary = InvoiceSummary(id="7", invoiceNumber="RE-TEST-1", contact_name="Max Mustermann")
    client = _InvoiceClientStub([summary])
    mailer = _MailServiceStub()
    repo = _RepoStub(
        {
            "rechnungen.fulfillment_mail_subject": "Rechnung {{invoice_number}}",
            "rechnungen.fulfillment_mail_template_html": "Hallo {{customer_name}},\n\nRE={{invoice_number}}",
        }
    )
    svc = InvoiceProcessingService(AppConfig(), client, repo, None, mailer)  # type: ignore[arg-type]

    flags = svc._run_mail_step(summary, svc.read_fulfillment_flags("7"))  # noqa: SLF001

    assert flags.mail_sent is True
    assert client.mail_calls[0]["to_email"] == "max@example.test"
    assert client.mail_calls[0]["subject"] == "Rechnung RE-TEST-1"
    assert "Hallo Max Mustermann" in str(client.mail_calls[0]["text"])
    assert mailer.calls == []
    assert client.render_calls == []


def test_mail_step_honors_recipient_override() -> None:
    summary = InvoiceSummary(id="8", invoiceNumber="RE-TEST-2", contact_name="Max Mustermann")
    client = _InvoiceClientStub([summary])
    mailer = _MailServiceStub()
    svc = InvoiceProcessingService(AppConfig(), client, _RepoStub({}), None, mailer)  # type: ignore[arg-type]

    flags = svc._run_mail_step(  # noqa: SLF001
        summary,
        svc.read_fulfillment_flags("8"),
        recipient_override="bernhard.holl@gmx.at",
    )

    assert flags.mail_sent is True
    assert client.mail_calls[0]["to_email"] == "bernhard.holl@gmx.at"
    assert mailer.calls == []


def test_manual_send_invoice_mail_uses_same_sevdesk_template_path() -> None:
    summary = InvoiceSummary(id="8a", invoiceNumber="RE-TEST-8A", contact_name="Max Mustermann")
    client = _InvoiceClientStub([summary])
    mailer = _MailServiceStub()
    repo = _RepoStub(
        {
            "rechnungen.fulfillment_mail_subject": "Rechnung {{invoice_number}}",
            "rechnungen.fulfillment_mail_template_html": "Hallo {{customer_name}},\n\nAnbei {{invoice_number}}",
        }
    )
    svc = InvoiceProcessingService(AppConfig(), client, repo, None, mailer)  # type: ignore[arg-type]

    flags, recipient, subject = svc.send_invoice_mail_for_invoice(summary)

    assert flags.mail_sent is True
    assert recipient == "max@example.test"
    assert subject == "Rechnung RE-TEST-8A"
    assert client.mail_calls[0]["to_email"] == "max@example.test"
    assert "Hallo Max Mustermann" in str(client.mail_calls[0]["text"])
    assert mailer.calls == []


def test_product_step_marks_digital_fulfilled_without_warning() -> None:
    summary = InvoiceSummary(id="9", invoiceNumber="RE-TEST-9", order_reference="12345")
    wix = _WixOrdersStub()
    wix._digital_only = True
    wix._fulfillment_status = "FULFILLED"
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([summary]),  # type: ignore[arg-type]
        None,
        wix,  # type: ignore[arg-type]
    )

    flags = svc._run_product_step(summary, svc.read_fulfillment_flags("9"))  # noqa: SLF001

    assert flags.product_ready is True
    assert flags.wix_fulfilled is True
    assert flags.last_warning == ""


def test_product_step_returns_warning_for_unconfirmed_physical_fulfillment() -> None:
    summary = InvoiceSummary(id="10", invoiceNumber="RE-TEST-10", order_reference="54321")
    wix = _WixOrdersStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([summary]),  # type: ignore[arg-type]
        None,
        wix,  # type: ignore[arg-type]
    )

    flags = svc._run_product_step(summary, svc.read_fulfillment_flags("10"))  # noqa: SLF001

    assert flags.product_ready is True
    assert flags.wix_fulfilled is False
    assert "Wix-Fulfillment nicht bestaetigt" in flags.last_warning


def test_invoice_list_hints_follow_legacy_alarm_rules() -> None:
    wix = _WixOrdersStub()
    wix.orders["20519"] = {
        "buyerNote": "Bitte rasch liefern",
        "shipping_lines": ["Max Muster", "Via Roma 1", "00100 Rom", "Italy"],
        "billing_lines": ["Max Muster", "Hauptplatz 1", "8010 Graz", "Austria"],
        "lineItems": [
            {"physicalProperties": {"sku": "XW-700.1"}},
            {"physicalProperties": {"sku": "XW-100"}},
        ],
    }
    repo = _RepoStub(
        {
            "rechnungen.allowed_country_codes": json.dumps(["Austria", "Germany"]),
            "rechnungen.sku_flags": json.dumps({"exact": ["XW-010"], "prefixes": ["XW-7"]}),
        }
    )
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([]),  # type: ignore[arg-type]
        repo,
        wix,  # type: ignore[arg-type]
    )

    hints = svc.resolve_invoice_list_hints("20519")

    assert hints.buyer_note == "Bitte rasch liefern"
    assert hints.address_mismatch is True
    assert hints.unreleased_sku is True
    assert hints.country_invalid is True
    assert hints.icon_keys() == ["print", "note", "alternateshippingaddress", "country"]
    assert "Lieferland außerhalb Freigabe" in hints.tooltip()


def test_start_fullflow_repairs_draft_products_before_finalize() -> None:
    summary = InvoiceSummary(id="11", invoiceNumber="RE-TEST-11", order_reference="20519")
    client = _InvoiceClientStub([summary])
    wix = _WixOrdersStub()
    mailer = _MailServiceStub()
    drafts = _DraftServiceStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        wix,  # type: ignore[arg-type]
        mailer,  # type: ignore[arg-type]
        drafts,  # type: ignore[arg-type]
    )

    result = svc.run_start_fullflow(full_mode=False)

    assert result["successful"] == 1
    assert drafts.calls == [("11", "20519")]
    assert not hasattr(client, "last_send_document")
    assert client.mail_calls[0]["invoice_id"] == "11"
    assert mailer.calls == []


def test_start_fullflow_processes_only_requested_invoice_ids() -> None:
    rows = [
        InvoiceSummary(id="11", invoiceNumber="RE-TEST-11"),
        InvoiceSummary(id="12", invoiceNumber="RE-TEST-12"),
    ]
    client = _InvoiceClientStub(rows)
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        None,
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    result = svc.run_start_fullflow(full_mode=False, invoice_ids=["12"])

    assert result["processed"] == 1
    assert result["successful"] == 1
    assert not hasattr(client, "last_send_document")
    assert client.mail_calls[0]["invoice_id"] == "12"


def test_inventory_requirements_use_only_requested_invoice_ids() -> None:
    rows = [
        InvoiceSummary(id="11", invoiceNumber="RE-TEST-11", order_reference="ORDER-11"),
        InvoiceSummary(id="12", invoiceNumber="RE-TEST-12", order_reference="ORDER-12"),
    ]
    client = _InvoiceClientStub(rows)
    wix = _WixOrdersStub()
    wix.line_items = {
        "ORDER-11": [SimpleNamespace(sku="XW-100", qty=5)],
        "ORDER-12": [
            SimpleNamespace(sku="xw-200", qty=2),
            SimpleNamespace(sku="XW-200", qty=1),
        ],
    }
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        wix,  # type: ignore[arg-type]
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    requirements = svc.build_inventory_requirements(invoice_ids=["12"])

    assert requirements == {"XW-200": 3}


def test_send_invoice_mail_uses_sevdesk_when_graph_unconfigured() -> None:
    summary = InvoiceSummary(id="11", invoiceNumber="RE-TEST-11", order_reference="")
    client = _InvoiceClientStub([summary])
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        None,
        _MailServiceStub(configured=False),  # type: ignore[arg-type]
    )

    _flags, recipient, _subject = svc.send_invoice_mail_for_invoice(summary)

    assert recipient == "max@example.test"
    assert client.mail_calls[0]["invoice_id"] == "11"
    assert client.mail_calls[0]["to_email"] == "max@example.test"


def test_send_invoice_mail_falls_back_to_graph_when_sevdesk_fails() -> None:
    summary = InvoiceSummary(id="12", invoiceNumber="RE-TEST-12", order_reference="")
    client = _InvoiceClientStub([summary])
    client.fail_mail = True
    mailer = _MailServiceStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        None,
        mailer,  # type: ignore[arg-type]
    )

    _flags, recipient, _subject = svc.send_invoice_mail_for_invoice(summary)

    assert recipient == "max@example.test"
    assert client.mail_calls == []
    assert mailer.calls[0]["to_email"] == "max@example.test"
    assert len(mailer.calls[0]["attachments"]) == 1


def test_send_invoice_mail_skips_graph_fallback_if_sevdesk_marked_sent_after_error() -> None:
    summary = InvoiceSummary(id="12b", invoiceNumber="RE-TEST-12B", order_reference="")
    client = _InvoiceClientStub([summary])
    client.fail_mail = True
    client.invoice_payloads["12b"] = {
        "id": "12b",
        "invoiceNumber": "RE-TEST-12B",
        "sendType": "VM",
        "contact": {"emails": [{"value": "max@example.test"}]},
    }
    mailer = _MailServiceStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        None,
        mailer,  # type: ignore[arg-type]
    )

    flags, recipient, _subject = svc.send_invoice_mail_for_invoice(summary)

    assert flags.mail_sent is True
    assert recipient == "max@example.test"
    assert client.mail_calls == []
    assert mailer.calls == []


def test_send_invoice_mail_skips_when_sevdesk_invoice_already_sent() -> None:
    summary = InvoiceSummary(id="13", invoiceNumber="RE-TEST-13", order_reference="")
    client = _InvoiceClientStub([summary])
    client.invoice_payloads["13"] = {
        "id": "13",
        "invoiceNumber": "RE-TEST-13",
        "sendType": "VM",
        "contact": {"emails": [{"value": "max@example.test"}]},
    }
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        None,
        _MailServiceStub(configured=False),  # type: ignore[arg-type]
    )

    flags, recipient, subject = svc.send_invoice_mail_for_invoice(summary)

    assert flags.mail_sent is True
    assert recipient == "max@example.test"
    assert subject == "Ihre Rechnung RE-TEST-13"
    assert client.mail_calls == []


def test_send_invoice_mail_skips_when_internal_mail_flag_already_set() -> None:
    summary = InvoiceSummary(id="14", invoiceNumber="RE-TEST-14", order_reference="")
    client = _InvoiceClientStub([summary])
    repo = _RepoStub(
        {
            "rechnungen.fulfillment_status": json.dumps(
                {
                    "14": {
                        "mail_sent": True,
                    }
                }
            )
        }
    )
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        repo,
        None,
        _MailServiceStub(configured=False),  # type: ignore[arg-type]
    )

    flags, recipient, _subject = svc.send_invoice_mail_for_invoice(summary)

    assert flags.mail_sent is True
    assert recipient == "max@example.test"
    assert client.mail_calls == []
