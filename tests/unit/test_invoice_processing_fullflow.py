"""Tests for invoice processing fullflow orchestration and persistence."""
from __future__ import annotations

import json

from xw_office.core.config import AppConfig
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.invoice_processing.service import FulfillmentFlags


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
