import datetime

from xw_office.services.product_hub.sevdesk_history_audit import (
    SevdeskHistoryProviderAdapter,
    audit_sevdesk_history,
)


class _Provider:
    def list_invoices_for_year(self, year: int):
        return [
            {"id": f"inv-{year}", "status": 200, "invoiceDate": f"{year}-01-15"},
            {"id": f"draft-{year}", "status": 100, "invoiceDate": f"{year}-01-20"},
        ]

    def list_invoice_positions(self, invoice_id: str):
        return [{"quantity": 2, "part": {"number": "SKU-1"}}]

    def list_credit_notes_for_year(self, year: int):
        return [{"id": f"credit-{year}", "status": 200, "creditNoteDate": f"{year}-02-15"}]

    def list_credit_note_positions(self, credit_note_id: str):
        return [{"quantity": 1, "part": {"number": "SKU-1"}}]


def test_history_audit_ignores_drafts_and_subtracts_credits() -> None:
    report = audit_sevdesk_history(_Provider(), as_of=datetime.date(2026, 11, 8))
    assert report.invoice_count == 5
    assert report.credit_note_count == 5
    assert report.product_position_count == 10
    assert report.net_units == 5
    assert report.full_months_covered == 60
    assert report.complete_five_year_window is True


def test_history_audit_reports_missing_sku() -> None:
    class MissingSku(_Provider):
        def list_invoice_positions(self, invoice_id: str):
            return [{"quantity": 1}]

    report = audit_sevdesk_history(MissingSku(), as_of=datetime.date(2026, 11, 8))
    assert any("ohne SKU" in issue for issue in report.issues)


def test_history_provider_adapter_groups_months_and_deduplicates_ids() -> None:
    class Monthly:
        def load_invoices(self, year: int, month: int):
            return [{"id": "inv-1", "month": month}] if month in {1, 2} else []

        def load_credit_notes(self, year: int, month: int):
            return [{"id": "credit-1", "month": month}] if month in {3, 4} else []

        def load_positions(self, resource: str, document_id: str):
            return [{"resource": resource, "id": document_id}]

    adapter = SevdeskHistoryProviderAdapter(Monthly())
    assert adapter.list_invoices_for_year(2026) == [{"id": "inv-1", "month": 1}]
    assert adapter.list_credit_notes_for_year(2026) == [{"id": "credit-1", "month": 3}]
    assert adapter.list_invoice_positions("inv-1")[0]["resource"] == "Invoice"
