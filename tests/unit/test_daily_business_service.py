"""Tests for daily business queue normalization and urgency markers."""
from __future__ import annotations

import json

from xw_studio.services.daily_business.service import DailyBusinessService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary


class _RepoStub:
    def __init__(self, payloads: dict[str, str]) -> None:
        self._payloads = payloads

    def get_value_json(self, key: str) -> str | None:
        return self._payloads.get(key)


class _InvoiceProcessingStub:
    def __init__(self, rows: list[InvoiceSummary]) -> None:
        self._rows = rows

    def load_invoice_summaries(
        self,
        *,
        status: int | None = None,
        limit: int = 300,
        offset: int = 0,
    ) -> list[InvoiceSummary]:
        return list(self._rows)


def test_mollie_queue_marks_auth_as_urgent() -> None:
    repo = _RepoStub(
        {
            "daily_business.queue.mollie": json.dumps(
                [{"ref": "M1", "status": "Authorized pending", "note": "missing auth"}]
            )
        }
    )
    svc = DailyBusinessService(repo)  # type: ignore[arg-type]

    rows = svc.load_queue_rows("mollie")

    assert len(rows) == 1
    assert rows[0]["Mark."] == "🔴"
    assert "Mollie-Auth" in rows[0]["__tooltip__Mark."]


def test_download_queue_no_urgency_when_clean() -> None:
    repo = _RepoStub(
        {
            "daily_business.queue.downloads": json.dumps(
                [{"ref": "D1", "status": "Bereit", "note": "Link gesendet"}]
            )
        }
    )
    svc = DailyBusinessService(repo)  # type: ignore[arg-type]

    rows = svc.load_queue_rows("downloads")

    assert len(rows) == 1
    assert rows[0]["Mark."] == ""


def test_custom_urgency_rules_from_settings_override_defaults() -> None:
    repo = _RepoStub(
        {
            "daily_business.urgency_rules": json.dumps(
                {
                    "generic": ["needs-review"],
                    "downloads": ["manual check"],
                }
            ),
            "daily_business.queue.downloads": json.dumps(
                [{"ref": "D2", "status": "READY", "note": "manual check by team"}]
            ),
        }
    )
    svc = DailyBusinessService(repo)  # type: ignore[arg-type]

    rows = svc.load_queue_rows("downloads")

    assert len(rows) == 1
    assert rows[0]["Mark."] == "🔴"
    assert "Download-Link" in rows[0]["__tooltip__Mark."]


def test_live_importer_classifies_open_invoices_into_queues() -> None:
    rows = [
        InvoiceSummary.model_validate(
            {
                "id": "1",
                "invoiceNumber": "RE-1",
                "contact_name": "Kunde A",
                "buyer_note": "Bitte refund veranlassen",
                "sumGross": "19.90",
                "status": 200,
            }
        ),
        InvoiceSummary.model_validate(
            {
                "id": "2",
                "invoiceNumber": "RE-2",
                "contact_name": "Kunde B",
                "order_reference": "MOLLIE AUTH PENDING",
                "sumGross": "9.90",
                "status": 200,
            }
        ),
        InvoiceSummary.model_validate(
            {
                "id": "3",
                "invoiceNumber": "RE-3",
                "contact_name": "Kunde C",
                "buyer_note": "Offene Ueberweisung mit EPC QR erstellen",
                "sumGross": "29.90",
                "status": 200,
            }
        ),
    ]
    svc = DailyBusinessService(_RepoStub({}), _InvoiceProcessingStub(rows))  # type: ignore[arg-type]

    refunds = svc.load_queue_rows("refunds")
    mollie = svc.load_queue_rows("mollie")
    transfers = svc.load_queue_rows("transfers")

    assert len(refunds) == 1
    assert refunds[0]["Ref"] == "RE-1"
    assert len(mollie) == 1
    assert mollie[0]["Ref"] == "RE-2"
    assert len(transfers) == 1
    assert transfers[0]["Ref"] == "RE-3"


def test_load_counts_uses_live_rows_when_pending_counts_missing() -> None:
    rows = [
        InvoiceSummary.model_validate(
            {
                "id": "10",
                "invoiceNumber": "RE-10",
                "order_reference": "download link fehlt",
                "status": 200,
            }
        )
    ]
    svc = DailyBusinessService(_RepoStub({}), _InvoiceProcessingStub(rows))  # type: ignore[arg-type]

    counts = svc.load_counts(open_invoice_count=7)

    assert counts["rechnungen"] == 7
    assert counts["downloads"] == 1
