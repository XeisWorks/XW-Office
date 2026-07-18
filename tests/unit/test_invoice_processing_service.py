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
        self.check_accounts = {"Stripe": 11, "Mollie": 12}
        self.linked_transactions: dict[int, list[dict[str, object]]] = {}
        self.existing_transactions: dict[int, list[dict[str, object]]] = {}
        self.created_transactions: list[dict[str, object]] = []
        self.booked_transactions: list[dict[str, object]] = []
        self.book_result_status = "booked"

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

    @staticmethod
    def invoice_reference(invoice: dict[str, object]) -> str:
        for key in ("reference", "customerInternalNote", "customerInternalNoteText", "referenceNumber", "orderNumber"):
            value = str(invoice.get(key) or "").strip()
            if value:
                return value
        return ""

    def get_check_account_id_by_name(self, name: str, *, preferred_types: tuple[str, ...] = ()) -> int | None:
        return self.check_accounts.get(name)

    def get_invoice_check_account_transactions(self, invoice_id: int) -> list[dict[str, object]]:
        return list(self.linked_transactions.get(invoice_id, []))

    def find_check_account_transactions(
        self,
        check_account_id: int,
        *,
        purpose: str = "",
        start_date: object = None,
        end_date: object = None,
    ) -> list[dict[str, object]]:
        rows = list(self.existing_transactions.get(check_account_id, []))
        if not purpose:
            return rows
        exact = str(purpose).strip().casefold()
        return [row for row in rows if str(row.get("paymtPurpose") or "").strip().casefold() == exact]

    def create_check_account_transaction(
        self,
        check_account_id: int,
        amount: float,
        *,
        value_date: object,
        payee: str,
        purpose: str,
    ) -> int:
        tx_id = 900 + len(self.created_transactions)
        payload = {
            "id": tx_id,
            "check_account_id": check_account_id,
            "amount": amount,
            "value_date": value_date,
            "payee": payee,
            "purpose": purpose,
        }
        self.created_transactions.append(payload)
        self.existing_transactions.setdefault(check_account_id, []).append(
            {"id": tx_id, "paymtPurpose": purpose}
        )
        return tx_id

    def book_invoice_with_transaction(
        self,
        invoice_id: int,
        amount: float,
        *,
        check_account_id: int,
        transaction_id: int,
        booking_date: int,
    ) -> dict[str, object]:
        self.booked_transactions.append(
            {
                "invoice_id": invoice_id,
                "amount": amount,
                "check_account_id": check_account_id,
                "transaction_id": transaction_id,
                "booking_date": booking_date,
            }
        )
        if self.book_result_status in {"booked", "already_booked", "invoice_already_paid"}:
            self.linked_transactions.setdefault(invoice_id, []).append({"id": transaction_id})
        return {
            "status": self.book_result_status,
            "invoice_status": "200" if self.book_result_status == "not_booked" else "1000",
            "tx_status": "100" if self.book_result_status == "not_booked" else "400",
        }


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
        self.payment_details: dict[str, dict[str, object]] = {}

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

    def physical_fulfillment_line_items(self, reference: str) -> list[dict[str, object]]:
        order = self.orders.get(reference, {})
        raw_items = order.get("lineItems") if isinstance(order.get("lineItems"), list) else []
        items: list[dict[str, object]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item_id = str(raw.get("id") or "").strip()
            if item_id:
                items.append({"id": item_id, "quantity": int(raw.get("quantity") or 1)})
        return items

    def create_fulfillment(self, reference: str, items: list[dict[str, str]]) -> dict[str, str]:
        self._created_fulfillment = (reference, list(items))
        return {"id": "fulfillment-1"} if items else {}

    def fulfillment_status(self, reference: str) -> str:
        return self._fulfillment_status

    def fetch_order_line_items(self, reference: str) -> list[object]:
        return list(self.line_items.get(reference, []))

    def fetch_order_payment_details(self, order_id: str) -> dict[str, object]:
        return dict(self.payment_details.get(order_id, {}))


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
    assert svc.is_flagged_sku("XW-561.14-P") is True
    assert svc.is_flagged_sku("XW-9999") is False


def test_sku_flags_support_custom_suffixes_for_hints_and_orders() -> None:
    rows = [
        InvoiceSummary(
            id="3p",
            invoice_number="R-3P",
            order_reference="WIX XW-561.14-P",
            has_unreleased_sku=False,
        )
    ]
    repo = _RepoStub(
        {
            "rechnungen.sku_flags": json.dumps(
                {
                    "exact": [],
                    "prefixes": [],
                    "suffixes": ["-P"],
                }
            )
        }
    )
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(rows), repo)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert result[0].has_unreleased_sku is True
    assert svc.is_flagged_sku("XW-561.14-P") is True
    assert svc._order_has_flagged_sku(  # noqa: SLF001
        {"lineItems": [{"physicalProperties": {"sku": "XW-561.14-P"}}]}
    ) is True
    assert svc.is_flagged_sku("XW-561.14") is False


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
    assert context["shipping_lines"] == ["Alt Kunde", "Hauptstrasse 7", "8010 Graz", "AUSTRIA"]


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
    assert client.mail_calls[0]["copy"] is False
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


def test_product_step_falls_back_to_physical_order_line_items() -> None:
    summary = InvoiceSummary(id="10b", invoiceNumber="RE-TEST-10B", order_reference="54321")
    wix = _WixOrdersStub()
    wix.orders["54321"] = {
        "lineItems": [
            {"id": "physical-1", "quantity": 2, "itemType": {"preset": "PHYSICAL"}},
        ]
    }
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([summary]),  # type: ignore[arg-type]
        None,
        wix,  # type: ignore[arg-type]
    )

    flags = svc._run_product_step(summary, svc.read_fulfillment_flags("10b"))  # noqa: SLF001

    assert flags.product_ready is True
    assert flags.wix_fulfilled is True
    assert wix._created_fulfillment == ("54321", [{"id": "physical-1", "quantity": 2}])


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


def test_start_fullflow_recovers_invoice_by_wix_reference_after_product_creation() -> None:
    stale = InvoiceSummary(id="old-11", invoiceNumber="RE-OLD", order_reference="20519")
    current = InvoiceSummary(id="new-11", invoiceNumber="RE-NEW", order_reference="20519")

    class RecoveringClient(_InvoiceClientStub):
        def __init__(self) -> None:
            super().__init__([stale])
            self.list_calls = 0

        def list_invoice_summaries(self, *, limit: int = 50, offset: int = 0, status: int | None = None):
            if offset > 0:
                return []
            self.list_calls += 1
            return [stale] if self.list_calls == 1 else [current]

        def fetch_invoice_by_id(self, invoice_id: str) -> dict[str, object]:
            if invoice_id == "old-11":
                return {}
            return {
                "id": invoice_id,
                "invoiceNumber": "RE-NEW",
                "customerInternalNote": "20519",
                "name": "Max Mustermann",
                "contact": {"emails": [{"value": "max@example.test"}]},
            }

    client = RecoveringClient()
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        None,
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    result = svc.run_start_fullflow(full_mode=False)

    assert result["processed"] == 1
    assert result["successful"] == 1
    assert client.mail_calls[0]["invoice_id"] == "new-11"


def test_start_fullflow_auto_books_paid_wix_payment() -> None:
    summary = InvoiceSummary(id="21", invoiceNumber="RE-TEST-21", order_reference="20519", sum_gross="29.90")
    client = _InvoiceClientStub([summary])
    client.invoice_payloads["21"] = {
        "id": "21",
        "invoiceNumber": "RE-TEST-21",
        "sumGross": "29.90",
        "customerInternalNote": "20519",
        "contact": {"emails": [{"value": "max@example.test"}]},
    }
    wix = _WixOrdersStub()
    wix.orders["20519"] = {
        "id": "wix-order-21",
        "buyerInfo": {"firstName": "Max", "lastName": "Mustermann", "email": "max@example.test"},
    }
    wix.payment_details["wix-order-21"] = {
        "paymentStatus": "PAID",
        "provider": "mollie",
        "providerTransactionId": "tr_123",
        "paymentCreatedDate": "2026-06-01T10:00:00Z",
        "amount": "29.90",
    }
    repo = _RepoStub({})
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        repo,
        wix,  # type: ignore[arg-type]
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    result = svc.run_start_fullflow(full_mode=False)

    assert result["successful"] == 1
    assert len(client.created_transactions) == 1
    assert len(client.booked_transactions) == 1
    assert client.created_transactions[0]["payee"] == "Max Mustermann [RE-TEST-21]"
    flags = svc.read_fulfillment_flags("21")
    assert flags.payment_applicable is True
    assert flags.payment_booked is True


def test_start_fullflow_uses_same_payee_format_for_stripe() -> None:
    summary = InvoiceSummary(id="25", invoiceNumber="RE-TEST-25", order_reference="20519", sum_gross="29.90")
    client = _InvoiceClientStub([summary])
    client.invoice_payloads["25"] = {
        "id": "25",
        "invoiceNumber": "RE-TEST-25",
        "sumGross": "29.90",
        "customerInternalNote": "20519",
        "contact": {"emails": [{"value": "max@example.test"}]},
    }
    wix = _WixOrdersStub()
    wix.orders["20519"] = {
        "id": "wix-order-21s",
        "buyerInfo": {"firstName": "Max", "lastName": "Mustermann", "email": "max@example.test"},
    }
    wix.payment_details["wix-order-21s"] = {
        "paymentStatus": "PAID",
        "provider": "stripe",
        "providerTransactionId": "pi_123",
        "paymentCreatedDate": "2026-06-01T10:00:00Z",
        "amount": "29.90",
    }
    repo = _RepoStub({})
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        repo,
        wix,  # type: ignore[arg-type]
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    result = svc.run_start_fullflow(full_mode=False)

    assert result["successful"] == 1
    assert len(client.created_transactions) == 1
    assert client.created_transactions[0]["payee"] == "Max Mustermann [RE-TEST-25]"
    assert len(client.booked_transactions) == 1


def test_start_fullflow_uses_billing_contact_name_for_payment_payee() -> None:
    summary = InvoiceSummary(id="26", invoiceNumber="RE-TEST-26", order_reference="20812", sum_gross="30.80")
    client = _InvoiceClientStub([summary])
    client.invoice_payloads["26"] = {
        "id": "26",
        "invoiceNumber": "RE-TEST-26",
        "sumGross": "30.80",
        "customerInternalNote": "20812",
        "contact": {"emails": [{"value": "nina@example.test"}]},
    }
    wix = _WixOrdersStub()
    wix.orders["20812"] = {
        "id": "wix-order-26",
        "buyerInfo": {"email": "nina@example.test"},
        "billingInfo": {
            "contactDetails": {"firstName": "Nina", "lastName": "Buehler"},
        },
    }
    wix.payment_details["wix-order-26"] = {
        "paymentStatus": "APPROVED",
        "provider": "mollie",
        "providerTransactionId": "ord_example_token",
        "paymentCreatedDate": "2026-06-12T19:11:19Z",
        "amount": "30.80",
    }
    repo = _RepoStub({})
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        repo,
        wix,  # type: ignore[arg-type]
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    result = svc.run_start_fullflow(full_mode=False)

    assert result["successful"] == 1
    assert len(client.created_transactions) == 1
    assert client.created_transactions[0]["payee"] == "Nina Buehler [RE-TEST-26]"
    assert len(client.booked_transactions) == 1


def test_start_fullflow_auto_books_approved_wix_payment() -> None:
    summary = InvoiceSummary(id="221", invoiceNumber="RE-TEST-21A", order_reference="20525", sum_gross="29.90")
    client = _InvoiceClientStub([summary])
    client.invoice_payloads["221"] = {
        "id": "221",
        "invoiceNumber": "RE-TEST-21A",
        "sumGross": "29.90",
        "customerInternalNote": "20525",
        "contact": {"emails": [{"value": "max@example.test"}]},
    }
    wix = _WixOrdersStub()
    wix.orders["20525"] = {
        "id": "wix-order-21a",
        "buyerInfo": {"firstName": "Max", "lastName": "Mustermann", "email": "max@example.test"},
    }
    wix.payment_details["wix-order-21a"] = {
        "paymentStatus": "APPROVED",
        "provider": "mollie",
        "providerTransactionId": "tr_approved",
        "paymentCreatedDate": "2026-06-01T10:00:00Z",
        "amount": "29.90",
    }
    repo = _RepoStub({})
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        repo,
        wix,  # type: ignore[arg-type]
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    flags = svc.retry_fulfillment_step("221", "payment_booked")

    assert flags.payment_applicable is True
    assert flags.payment_booked is True
    assert len(client.created_transactions) == 1
    assert len(client.booked_transactions) == 1


def test_retry_fulfillment_step_books_existing_assigned_payment() -> None:
    summary = InvoiceSummary(id="22", invoiceNumber="RE-TEST-22", order_reference="20520", sum_gross="29.90")
    client = _InvoiceClientStub([summary])
    client.invoice_payloads["22"] = {
        "id": "22",
        "invoiceNumber": "RE-TEST-22",
        "sumGross": "29.90",
        "customerInternalNote": "20520",
        "contact": {"emails": [{"value": "max@example.test"}]},
    }
    client.existing_transactions[12] = [
        {"id": 77, "paymtPurpose": "order:20520 | mollie:tr_retry | PAYMENT"}
    ]
    wix = _WixOrdersStub()
    wix.orders["20520"] = {
        "id": "wix-order-22",
        "buyerInfo": {"firstName": "Birgit", "lastName": "Mayr", "email": "birgit@example.test"},
    }
    wix.payment_details["wix-order-22"] = {
        "paymentStatus": "PAID",
        "provider": "mollie",
        "providerTransactionId": "tr_retry",
        "paymentCreatedDate": "2026-06-01T09:00:00Z",
        "amount": "29.90",
    }
    repo = _RepoStub(
        {
            "rechnungen.fulfillment_status": json.dumps(
                {"22": {"payment_applicable": True, "payment_booked": False}}
            )
        }
    )
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        repo,
        wix,  # type: ignore[arg-type]
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    flags = svc.retry_fulfillment_step("22", "payment_booked")

    assert flags.payment_booked is True
    assert client.created_transactions == []
    assert len(client.booked_transactions) == 1
    assert client.booked_transactions[0]["transaction_id"] == 77


def test_payment_step_does_not_short_circuit_on_linked_but_unpaid_invoice() -> None:
    summary = InvoiceSummary(id="23", invoiceNumber="RE-TEST-23", order_reference="20523", sum_gross="29.90")
    client = _InvoiceClientStub([summary])
    client.invoice_payloads["23"] = {
        "id": "23",
        "invoiceNumber": "RE-TEST-23",
        "status": 200,
        "sumOutstanding": "29.90",
        "sumGross": "29.90",
        "customerInternalNote": "20523",
        "contact": {"emails": [{"value": "max@example.test"}]},
    }
    client.linked_transactions[23] = [{"id": 701}]
    wix = _WixOrdersStub()
    wix.orders["20523"] = {
        "id": "wix-order-23",
        "buyerInfo": {"firstName": "Anna", "lastName": "Mair", "email": "anna@example.test"},
    }
    wix.payment_details["wix-order-23"] = {
        "paymentStatus": "PAID",
        "provider": "mollie",
        "providerTransactionId": "tr_linked_retry",
        "paymentCreatedDate": "2026-06-01T11:00:00Z",
        "amount": "29.90",
    }
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        wix,  # type: ignore[arg-type]
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    result = svc.run_start_fullflow(full_mode=False)

    assert result["successful"] == 1
    assert len(client.created_transactions) == 0
    assert len(client.booked_transactions) == 1
    assert client.booked_transactions[0]["transaction_id"] == 701
    flags = svc.read_fulfillment_flags("23")
    assert flags.payment_booked is True


def test_payment_step_surfaces_not_booked_status_as_warning() -> None:
    summary = InvoiceSummary(id="24", invoiceNumber="RE-TEST-24", order_reference="20524", sum_gross="29.90")
    client = _InvoiceClientStub([summary])
    client.book_result_status = "not_booked"
    client.invoice_payloads["24"] = {
        "id": "24",
        "invoiceNumber": "RE-TEST-24",
        "status": 200,
        "sumOutstanding": "29.90",
        "sumGross": "29.90",
        "customerInternalNote": "20524",
        "contact": {"emails": [{"value": "max@example.test"}]},
    }
    wix = _WixOrdersStub()
    wix.orders["20524"] = {
        "id": "wix-order-24",
        "buyerInfo": {"firstName": "Paul", "lastName": "Leitner", "email": "paul@example.test"},
    }
    wix.payment_details["wix-order-24"] = {
        "paymentStatus": "PAID",
        "provider": "mollie",
        "providerTransactionId": "tr_notbooked",
        "paymentCreatedDate": "2026-06-01T11:30:00Z",
        "amount": "29.90",
    }
    repo = _RepoStub(
        {
            "rechnungen.fulfillment_status": json.dumps(
                {"24": {"payment_applicable": True, "payment_booked": False}}
            )
        }
    )
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        repo,
        wix,  # type: ignore[arg-type]
        _MailServiceStub(),  # type: ignore[arg-type]
    )

    flags = svc.retry_fulfillment_step("24", "payment_booked")

    assert len(client.booked_transactions) == 1
    assert flags.payment_booked is False
    assert "status=not_booked" in flags.last_warning


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
