from __future__ import annotations

from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


def test_invoice_preview_export_writes_rendered_pdf_without_fulfillment_effects(
    monkeypatch: object,
    tmp_path: object,
) -> None:
    service = object.__new__(InvoiceProcessingService)
    summary = InvoiceSummary(id="inv-42", invoiceNumber="RE 42")
    calls: list[str] = []

    def load_summary(invoice_id: str) -> InvoiceSummary:
        calls.append(f"summary:{invoice_id}")
        return summary

    def load_pdf(invoice_id: str, *, expected_invoice_number: str = "") -> bytes:
        calls.append(f"pdf:{invoice_id}:{expected_invoice_number}")
        return b"%PDF-1.4 preview"

    monkeypatch.setattr(service, "_load_summary_by_id", load_summary)
    monkeypatch.setattr(service, "_get_invoice_pdf_bytes", load_pdf)

    exported = service.export_invoice_preview_pdf("inv-42", tmp_path)

    assert exported.parent == tmp_path
    assert exported.name.startswith("RE_42_")
    assert exported.suffix == ".pdf"
    assert exported.read_bytes() == b"%PDF-1.4 preview"
    assert calls == ["summary:inv-42", "pdf:inv-42:RE 42"]
