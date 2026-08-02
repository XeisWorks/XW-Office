"""Tests for invoice counting without UI hard limits."""
from __future__ import annotations

from xw_office.core.config import AppConfig
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


class _InvoiceClientStub:
    def __init__(self, pages: list[list[InvoiceSummary]]) -> None:
        self._pages = pages

    def list_invoice_summaries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: int | None = None,
    ) -> list[InvoiceSummary]:
        page_index = 0 if limit == 0 else offset // limit
        if 0 <= page_index < len(self._pages):
            return list(self._pages[page_index])
        return []


def _row(i: int) -> InvoiceSummary:
    return InvoiceSummary(id=str(i), invoice_number=f"R-{i}", status_code=200)


def test_count_invoices_pages_until_last_partial_page() -> None:
    pages = [
        [_row(i) for i in range(200)],
        [_row(i) for i in range(200, 400)],
        [_row(i) for i in range(400, 451)],
    ]
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(pages))  # type: ignore[arg-type]

    total = svc.count_invoices(status=200, batch_size=200)

    assert total == 451


def test_count_invoices_empty() -> None:
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub([[]]))  # type: ignore[arg-type]

    total = svc.count_invoices(status=200)

    assert total == 0
