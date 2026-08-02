"""Tests for CRM merge preflight (blocked-invoice classification)."""
from __future__ import annotations

from xw_office.services.crm.preflight import build_preflight_report, classify_invoice_for_merge
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


def _invoice(
    *,
    status_code: int | None = 100,
    invoice_date: str | None = None,
    delivery_date: str | None = None,
) -> InvoiceSummary:
    # Mirrors real production data: sevDesk payloads use the alias keys
    # (status/invoiceDate/deliveryDate), parsed via from_api_object().
    raw: dict[str, object] = {"id": "1"}
    if status_code is not None:
        raw["status"] = status_code
    if invoice_date is not None:
        raw["invoiceDate"] = invoice_date
    if delivery_date is not None:
        raw["deliveryDate"] = delivery_date
    return InvoiceSummary.from_api_object(raw)


def test_draft_invoice_without_date_problem_is_movable() -> None:
    decision = classify_invoice_for_merge(_invoice(status_code=100))
    assert decision.movable is True


def test_finalized_invoice_is_blocked_as_enshrined() -> None:
    decision = classify_invoice_for_merge(_invoice(status_code=200))
    assert decision.movable is False
    assert "finalisiert" in decision.reason


def test_paid_invoice_is_blocked_as_enshrined() -> None:
    decision = classify_invoice_for_merge(_invoice(status_code=1000))
    assert decision.movable is False


def test_invoice_date_before_delivery_date_is_blocked() -> None:
    decision = classify_invoice_for_merge(
        _invoice(status_code=100, invoice_date="2026-05-01", delivery_date="2026-05-10")
    )
    assert decision.movable is False
    assert "Lieferdatum" in decision.reason


def test_invoice_date_after_delivery_date_is_movable() -> None:
    decision = classify_invoice_for_merge(
        _invoice(status_code=100, invoice_date="2026-05-10", delivery_date="2026-05-01")
    )
    assert decision.movable is True


def test_build_preflight_report_splits_movable_and_blocked() -> None:
    invoices = [
        _invoice(status_code=100),
        _invoice(status_code=200),
        _invoice(status_code=100, invoice_date="2026-05-01", delivery_date="2026-05-10"),
    ]

    report = build_preflight_report("contact-1", invoices)

    assert report.invoice_count == 3
    assert len(report.movable_invoices) == 1
    assert len(report.blocked_invoices) == 2
    assert report.has_blocked_invoices is True
    assert report.has_no_invoices is False


def test_build_preflight_report_with_no_invoices_is_safe() -> None:
    report = build_preflight_report("contact-1", [])
    assert report.has_no_invoices is True
    assert report.has_blocked_invoices is False
