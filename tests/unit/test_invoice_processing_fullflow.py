"""Tests for invoice processing fullflow orchestration and persistence."""
from __future__ import annotations

import json

from xw_office.core.config import AppConfig
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.invoice_processing.service import FulfillmentFlags
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


class _RepoStub:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self.values[key] = value_json


class _InvoiceClientStub:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def list_invoice_summaries(self, *, limit: int, offset: int, status: int | None = None):
        if offset > 0:
            return []
        if status != 100:
            return []
        return []


def test_fulfillment_flags_roundtrip_payload() -> None:
    flags = FulfillmentFlags(
        label_printed=True,
        invoice_printed=True,
        product_ready=False,
        mail_sent=True,
        wix_fulfilled=False,
        payment_applicable=True,
        payment_booked=False,
        last_run_iso="2026-04-04T08:00:00",
        last_error="",
    )
    payload = flags.as_row_payload()
    restored = FulfillmentFlags.from_payload(payload)
    assert restored.label_printed is True
    assert restored.mail_sent is True
    assert restored.payment_applicable is True
    assert restored.last_run_iso == "2026-04-04T08:00:00"


def test_write_and_read_fulfillment_flags() -> None:
    repo = _RepoStub()
    service = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(), repo, None)
    flags = FulfillmentFlags(invoice_printed=True, last_run_iso="2026-04-04T09:00:00")

    service.write_fulfillment_flags("123", flags)
    loaded = service.read_fulfillment_flags("123")

    assert loaded.invoice_printed is True
    assert loaded.last_run_iso == "2026-04-04T09:00:00"
    stored = json.loads(repo.values["rechnungen.fulfillment_status"])
    assert "123" in stored


def test_recovery_rows_do_not_enter_new_start_history(monkeypatch) -> None:
    service = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(), _RepoStub(), None)
    old = InvoiceSummary(id="old", contact_name="Alter Lauf")
    current = InvoiceSummary(id="new", contact_name="Neuer Lauf")
    monkeypatch.setattr(service, "_load_start_target_summaries", lambda **_kw: [current])
    monkeypatch.setattr(service, "filter_start_ready", lambda rows: rows)
    monkeypatch.setattr(service, "_resume_incomplete_fulfillment", lambda **_kw: {
        "processed": 1, "failures": 0, "successful": 1, "aborted": False,
        "run_summaries": [old],
    })
    monkeypatch.setattr(service, "_prefetch_wix_order_context", lambda _rows: None)
    monkeypatch.setattr(service, "_start_delivery_kind", lambda _row: "physical")
    monkeypatch.setattr(service, "_start_processing_priority", lambda _row, **_kw: (0,))
    monkeypatch.setattr(service, "_run_start_fullflow_print_first", lambda **_kw: {
        "processed": 1, "failures": 0, "successful": 1, "aborted": False,
        "run_summaries": [current], "successful_invoice_ids": ["new"],
    })

    result = service.run_start_fullflow(full_mode=True)
    assert [row.id for row in result["run_summaries"]] == ["new"]
    assert [row.id for row in result["resumed_summaries"]] == ["old"]


def test_start_refresh_preserves_embedded_contact_name(monkeypatch) -> None:
    service = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(), _RepoStub(), None)
    service._invoices.fetch_invoice_by_id = lambda _invoice_id: {"id": "42", "status": 200}
    monkeypatch.setattr(service, "_apply_sensitive_country_flags", lambda _rows: None)
    monkeypatch.setattr(service, "_apply_unreleased_sku_flags", lambda _rows: None)
    original = InvoiceSummary(id="42", contact_name="Anna Versand", invoiceDate="2026-11-17")

    refreshed = service._resolve_current_start_summary(original)
    finalized = service._refresh_finalized_start_summary(refreshed)
    assert finalized.contact_name == "Anna Versand"
    assert finalized.invoice_date == "2026-11-17"
