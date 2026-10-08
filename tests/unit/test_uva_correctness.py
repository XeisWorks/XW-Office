from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree as ET

import httpx
import pytest

from xw_office.core.config import AppConfig
from xw_office.core.exceptions import SevdeskApiError
from xw_office.services.finanzonline.source_reads import load_tax_resource
from xw_office.services.finanzonline.u30_xml import build_u30_xml, validate_u30_xml
from xw_office.services.finanzonline.amounts import tax_amount
from xw_office.services.finanzonline.uva_payload_service import UvaPayloadService
from xw_office.services.finanzonline.uva_preview import (
    SevdeskUvaPreviewProvider,
    UvaPreviewService,
)
from xw_office.services.finanzonline.uva_selection import UvaDocumentSelector
from xw_office.services.http_client import SevdeskConnection


def test_partial_payment_does_not_round_ratio_before_scaling() -> None:
    document = {
        "id": "precision", "paidDate": "2026-09-04", "status": "750",
        "sumGross": "120000.00", "sumNet": "100000.00", "sumTax": "20000.00",
        "xw_paid_amount": "100.00",
        "xw_positions": [{"sumNet": "100000.00", "sumTax": "20000.00"}],
    }
    result = UvaDocumentSelector().select_sales_documents(2026, 9, [document])
    selected = result.documents[0]
    assert selected["sumGross"] == "100.00"
    assert selected["sumNet"] == "83.33"
    assert selected["sumTax"] == "16.67"
    assert selected["xw_positions"][0]["sumNet"] == "83.33"
    assert result.stats.partial_scaled == 1
    assert document["sumGross"] == "120000.00"


def test_tiny_partial_payment_is_not_counted_as_full_invoice() -> None:
    result = UvaDocumentSelector().select_sales_documents(2026, 9, [{
        "id": "small", "paidDate": "2026-09-04", "status": "750",
        "sumGross": "120000.00", "sumNet": "100000.00", "sumTax": "20000.00",
        "xw_paid_amount": "1.00",
    }])
    assert result.documents[0]["sumGross"] == "1.00"


def test_payment_log_id_is_not_the_bank_transaction_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getCheckAccountTransactionLogs"):
            objects = [{
                "id": "log-row",
                "assignedAmount": "60.00",
                "checkAccountTransaction": {"id": "bank-tx", "valueDate": "2026-09-04"},
            }]
        else:
            objects = [{"id": "bank-tx", "valueDate": "2026-09-04", "amount": "120.00"}]
        return httpx.Response(200, json={"objects": objects})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        date, amount = provider._load_payment_metadata("Invoice", "1", 2026, 9)
    assert date is not None
    assert amount == "60.00"


@pytest.mark.parametrize("missing_date", [False, True])
def test_reconciled_logs_skip_transactions_only_when_dates_are_complete(missing_date: bool) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("getCheckAccountTransactionLogs"):
            objects = [{"id": "assignment", "assignedAmount": "60.00",
                        "checkAccountTransaction": {"id": "bank"}}]
            if not missing_date:
                objects[0]["bookingDate"] = "2026-09-04"
        else:
            objects = [{"id": "bank", "valueDate": "2026-09-04", "amount": "120.00"}]
        return httpx.Response(200, json={"objects": objects})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        _, amount = provider._load_payment_metadata(
            "Invoice", "1", 2026, 9, expected_paid_amount=Decimal("60")
        )
    assert amount == "60.00"
    assert len(calls) == (2 if missing_date else 1)


def test_dated_cumulative_payment_is_split_by_actual_month_and_distinct_assignments() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"objects": [
            {"id": "first", "amountPaid": "70", "bookingDate": "2026-08-04",
             "checkAccountTransaction": {"id": "bank"}},
            {"id": "second", "amountPaid": "30", "bookingDate": "2026-09-04",
             "checkAccountTransaction": {"id": "bank"}},
            {"id": "second", "amountPaid": "30", "bookingDate": "2026-09-04",
             "checkAccountTransaction": {"id": "bank"}},
        ]})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        enriched = provider._enrich_payment_metadata("Invoice", {
            "id": "1", "paidDate": "2026-09-04", "status": "750",
            "paidAmount": "100", "sumGross": "120", "sumNet": "100", "sumTax": "20",
        }, 2026, 9)
        selected = UvaDocumentSelector().select_sales_documents(2026, 9, [enriched])
    assert enriched["xw_paid_amount"] == "30.00"
    assert selected.documents[0]["sumGross"] == "30.00"


def test_discount_adjusted_accounting_amount_is_not_scaled_twice() -> None:
    selected = UvaDocumentSelector().select_purchase_documents(2026, 9, [{
        "id": "discount", "paidDate": "2026-09-04", "status": "1000",
        "sumGross": "120", "sumNet": "100", "sumTax": "20",
        "sumGrossAccounting": "108", "sumNetAccounting": "90", "sumTaxAccounting": "18",
        "xw_paid_amount": "108", "taxText": "MIT 20% MEHRWERTSTEUER",
        "xw_positions": [{"sumNetAccounting": "90", "sumTaxAccounting": "18", "taxRate": "20"}],
    }])
    section = UvaPreviewService()._build_section(selected.documents, is_purchase=True)
    assert section.total_net == "90.00"
    assert section.total_vat == "18.00"
    assert selected.stats.partial_scaled == 0


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "not-an-amount"])
def test_invalid_amounts_cannot_become_zero_tax(value: str) -> None:
    with pytest.raises(ValueError):
        tax_amount(value)


def test_signed_output_tax_correction_is_exported_and_schema_valid() -> None:
    xml = build_u30_xml(
        {"jahr": 2026, "monat": 9, "kennzahlen": {"A000": "0", "D090": "-10"}},
        fastnr="989999999",
    )
    assert ET.fromstring(xml).findtext(".//KZ090") == "-10.00"
    validate_u30_xml(xml)


def test_single_rate_partial_payment_conserves_header_rounding() -> None:
    selected = UvaDocumentSelector().select_sales_documents(2026, 9, [{
        "id": "rounding", "status": "750", "paidDate": "2026-09-04",
        "sumGross": "120", "sumNet": "100", "sumTax": "20", "xw_paid_amount": "25",
        "taxText": "MIT 20% MEHRWERTSTEUER",
        "xw_positions": [
            {"sumNet": "33.33", "sumTax": "6.67", "taxRate": "20"} for _ in range(3)
        ],
    }])
    section = UvaPreviewService()._build_section(selected.documents, is_purchase=False)
    assert (section.total_net, section.total_vat, section.total_gross) == (
        "20.83", "4.17", "25.00"
    )


@pytest.mark.parametrize("position_net,blocking", [("100", False), ("50", True)])
def test_tip_is_advisory_but_net_discrepancy_blocks(position_net: str, blocking: bool) -> None:
    from xw_office.services.finanzonline.uva_service import build_data_quality

    warnings: list[str] = []
    UvaPreviewService()._build_section([{
        "id": "tip", "taxText": "MIT 20% MEHRWERTSTEUER",
        "sumGross": "130", "sumNet": "100", "sumTax": "20",
        "xw_positions": [{"sumNet": position_net, "sumTax": "20", "taxRate": "20"}],
    }], is_purchase=True, warnings=warnings)
    assert bool(build_data_quality({"warnings": warnings})["uva_blocking_count"]) == blocking
    assert warnings


def test_negative_base_is_visible_as_submission_blocker() -> None:
    from xw_office.services.finanzonline.uva_service import build_data_quality

    quality = build_data_quality({"kennzahlen": {"A022": "-10", "D090": "-2"}})
    assert quality["uva_blocking_count"] == 1
    assert quality["status"] == "blockiert"


def test_bulk_payment_evidence_is_complete_reused_and_refreshed() -> None:
    calls: list[str] = []
    paid = {"amount": "60"}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.url.path == "/CheckAccountTransactionLog"
        return httpx.Response(200, json={"objects": [{
            "id": "assignment", "object": {"id": "1", "objectName": "Invoice"},
            "amountPaid": paid["amount"], "bookingDate": "2026-09-04",
            "checkAccountTransaction": {"id": "bank"},
        }]})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        provider.prepare_payment_logs()
        _, first = provider._load_payment_metadata("Invoice", "1", 2026, 9, expected_paid_amount=Decimal("60"))
        paid["amount"] = "30"
        provider.clear_cache()
        provider.prepare_payment_logs()
        _, refreshed = provider._load_payment_metadata(
            "Invoice", "1", 2026, 9, expected_paid_amount=Decimal("30")
        )
    assert (first, refreshed) == ("60.00", "30.00")
    assert calls == ["/CheckAccountTransactionLog"] * 2


@pytest.mark.parametrize("first_payment,september_gross", [("60", "60.00"), ("120", "0.00")])
def test_overpayment_does_not_tax_the_same_invoice_again(first_payment: str, september_gross: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        rows = [
            {"id": "first", "amountPaid": first_payment, "bookingDate": "2026-08-04",
             "checkAccountTransaction": {"id": "bank-1"}},
            {"id": "second", "amountPaid": "70", "bookingDate": "2026-09-04",
             "checkAccountTransaction": {"id": "bank-2"}},
        ] if request.url.path.endswith("getCheckAccountTransactionLogs") else []
        return httpx.Response(200, json={"objects": rows})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        document = provider._enrich_payment_metadata("Invoice", {
            "id": "1", "status": "1000", "paidAmount": "120",
            "sumGross": "120", "sumNet": "100", "sumTax": "20",
            "invoiceDate": "2026-08-04",
        }, 2026, 9)
        selected = UvaDocumentSelector().select_sales_documents(2026, 9, [document])
    assert document["xw_paid_amount"] == september_gross
    assert provider.payment_warnings
    if september_gross == "0.00":
        assert selected.documents == []
    else:
        assert selected.documents[0]["sumGross"] == september_gross


def test_foreign_b2b_service_is_not_domestic_reverse_charge_base() -> None:
    from xw_office.services.finanzonline.uva_preview import UvaPreviewResult

    service = UvaPreviewService()
    sales = service._build_section([{
        "taxText": "Reverse Charge", "vatNumber": "DE136695976",
        "sumNet": "50", "sumTax": "0", "sumGross": "50",
    }], is_purchase=False)
    result = UvaPayloadService(service).build_payload_from_preview(
        UvaPreviewResult(
            year=2026, month=9, sales=sales,
            input_tax=service._build_section([], is_purchase=True),
        )
    )
    assert sales.total_net == "50.00"
    assert sales.groups[0].label == "REVERSE CHARGE (AUSLAND)"
    assert result.kennzahlen.A021 == result.kennzahlen.A000 == "0.00"


def test_rc_revenue_voucher_is_in_zm_by_document_not_payment_month() -> None:
    from xw_office.services.finanzonline.zm_service import SevdeskZmInvoiceProvider, ZmService

    def handler(request: httpx.Request) -> httpx.Response:
        rows: list[dict[str, Any]] = []
        if request.url.path == "/Voucher":
            rows = [{
                "id": "income", "creditDebit": "D", "status": "1000",
                "voucherDate": "2026-09-04", "payDate": "2026-10-01",
                "supplierNameAtSave": "EU Portal", "vatNumber": "DE136695976",
                "taxText": "Reverse Charge", "sumNetAccounting": "50.40", "sumNet": "51.00",
            }]
        return httpx.Response(200, json={"objects": rows})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        result = ZmService(SevdeskZmInvoiceProvider(SevdeskConnection(client, AppConfig()))).calculate_month(2026, 9)
    assert result.invalid == []
    assert len(result.rows) == 1
    assert result.rows[0].kind == "service"
    assert result.rows[0].amount_eur_int == 50


def test_complete_position_pagination_and_page_limit_failure() -> None:
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        return httpx.Response(200, json={"objects": (
            [{"id": "1"}, {"id": "2"}] if offset == 0 else [{"id": "3"}]
        )})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        connection = SevdeskConnection(client, AppConfig())
        rows = load_tax_resource(connection, "/InvoicePos", page_size=2)
        assert len(rows) == 3
        assert offsets == [0, 2]
        with pytest.raises(RuntimeError, match="nicht vollstaendig"):
            load_tax_resource(connection, "/InvoicePos", page_size=2, max_pages=1)


@pytest.mark.parametrize("objects", ["invalid", [None], [{"id": "1"}, "invalid"]])
def test_malformed_source_rows_are_not_silently_discarded(objects: Any) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"objects": objects})
        ), base_url="https://example.test",
    ) as client:
        with pytest.raises(ValueError, match="Objektliste"):
            load_tax_resource(SevdeskConnection(client, AppConfig()), "/Invoice")


@pytest.mark.parametrize("key", ["KZ000", "KZ011", "KZ017", "KZ022", "KZ070", "KZ072", "KZ060"])
def test_unsupported_negative_monthly_adjustments_are_not_silently_omitted(key: str) -> None:
    with pytest.raises(ValueError, match=key):
        build_u30_xml(
            {"jahr": 2026, "monat": 9, "kennzahlen": {"KZ000": "0.00", key: "-10.00"}},
            fastnr="989999999",
        )


def test_foreign_purchase_is_visible_but_not_deducted_in_at_uva() -> None:
    preview = UvaPreviewService()._build_section([{
        "taxText": "DEUTSCHE MWST. 7%", "sumNet": "100.00",
        "sumTax": "7.00", "sumGross": "107.00",
    }], is_purchase=True)
    assert preview.total_vat == "7.00"
    assert preview.groups[0].label == "DEUTSCHE MWST. 7%"
    values = {"C060": Decimal(0)}
    warnings: list[str] = []
    UvaPayloadService(UvaPreviewService())._apply_purchase_group(
        preview.groups[0], values, warnings
    )
    assert values["C060"] == Decimal(0)
    assert len(warnings) == 1


def test_explicit_position_rates_override_domestic_document_heading() -> None:
    section = UvaPreviewService()._build_section([{
        "taxText": "MIT 10% MEHRWERTSTEUER",
        "xw_positions": [
            {"sumNet": "100.00", "sumTax": "10.00", "taxRate": "10"},
            {"sumNet": "100.00", "sumTax": "20.00", "taxRate": "20"},
        ],
    }], is_purchase=False)
    assert {group.label: group.net_amount for group in section.groups} == {
        "MIT 10% MEHRWERTSTEUER": "100.00",
        "MIT 20% MEHRWERTSTEUER": "100.00",
    }


def test_zero_net_fully_discounted_shipping_is_not_reconstructed_from_price() -> None:
    section = UvaPreviewService()._build_section([{
        "taxText": "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)",
        "xw_positions": [
            {"sumNetAccounting": "27.30", "sumTaxAccounting": "0.00", "taxRate": "0"},
            {"sumNetAccounting": "0", "sumTaxAccounting": "0",
             "price": "5", "quantity": "1", "discount": "100", "taxRate": "0"},
        ],
    }], is_purchase=False)
    assert section.total_net == "27.30"
    assert section.total_gross == "27.30"


def test_unknown_tax_category_is_visible_and_blocks_uva_not_zm() -> None:
    from xw_office.services.finanzonline.uva_preview import UvaPreviewResult
    from xw_office.services.finanzonline.uva_service import build_data_quality

    service = UvaPreviewService()
    preview = UvaPreviewResult(
        year=2026, month=9,
        sales=service._build_section([{
            "taxText": "UNGEKLAERT", "sumNet": "100.00",
            "sumTax": "5.00", "sumGross": "105.00",
        }], is_purchase=False),
        input_tax=service._build_section([], is_purchase=True),
    )
    payload = UvaPayloadService(service).build_payload_from_preview(preview)
    quality = build_data_quality(payload.model_dump())
    assert preview.sales.total_vat == "5.00"
    assert payload.kennzahlen.A000 == "0.00"
    assert quality["uva_blocking_count"] == 1
    assert quality["zm_blocking_count"] == 0


def test_manually_paid_invoice_with_zero_paid_amount_is_not_zero_turnover() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"objects": []})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        provider.prepare_payment_logs()
        document = provider._enrich_payment_metadata("Invoice", {
            "id": "manual", "status": "1000", "paidDate": "2026-09-04",
            "paidAmount": "0", "sumGross": "120", "sumNet": "100", "sumTax": "20",
        }, 2026, 9)
        selected = UvaDocumentSelector().select_sales_documents(2026, 9, [document])
    assert selected.documents[0]["sumGross"] == "120"
    assert selected.stats.partial_scaled == 0
    assert calls == ["/CheckAccountTransactionLog"]


def test_explicit_zero_period_payment_excludes_invoice() -> None:
    selected = UvaDocumentSelector().select_sales_documents(2026, 9, [{
        "id": "settled", "status": "1000", "paidDate": "2026-09-04",
        "paidAmount": "120", "xw_paid_amount": "0", "sumGross": "120",
    }])
    assert selected.documents == []


@pytest.mark.parametrize("tax_text", [
    "REVERSE CHARGE", "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)",
])
def test_incoming_self_assessed_tax_is_not_scaled_by_payment(tax_text: str) -> None:
    selected = UvaDocumentSelector().select_purchase_documents(2026, 9, [{
        "id": "accrual", "status": "750", "voucherDate": "2026-09-04",
        "deliveryDate": "2026-09-04", "paidDate": "2026-10-04",
        "xw_paid_amount": "10", "sumNet": "100", "sumGross": "100", "sumTax": "0",
        "taxText": tax_text,
    }])
    assert selected.documents[0]["sumNet"] == "100"
    assert selected.stats.partial_scaled == 0
    assert selected.stats.accrual_selected == 1


def test_rc_performance_month_survives_provider_date_filter() -> None:
    document = {
        "id": "performance", "creditDebit": "C", "status": "150",
        "voucherDate": "2026-09-04", "deliveryDate": "2026-08-24",
        "payDate": "2026-10-04", "sumNet": "100", "sumTax": "0",
        "sumGross": "100", "taxText": "REVERSE CHARGE",
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"objects": []})),
        base_url="https://example.test",
    ) as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        provider._voucher_period_cache[(2026, 8)] = [document]
        provider._voucher_period_cache[(2026, 9)] = [document]
        august = provider.load_purchase_documents(2026, 8)
        september = provider.load_purchase_documents(2026, 9)
    selector = UvaDocumentSelector()
    assert selector.select_purchase_documents(2026, 8, august).documents[0]["sumNet"] == "100"
    assert selector.select_purchase_documents(2026, 9, september).documents == []


def test_domestic_prepaid_purchase_waits_for_invoice_without_losing_deduction() -> None:
    document = {
        "id": "advance", "status": "1000", "voucherDate": "2026-09-04",
        "paidDate": "2026-08-04", "sumNet": "100", "sumTax": "20",
        "sumGross": "120", "taxText": "MIT 20% MEHRWERTSTEUER",
    }
    selector = UvaDocumentSelector()
    assert selector.select_purchase_documents(2026, 8, [document]).documents == []
    assert selector.select_purchase_documents(2026, 9, [document]).documents[0]["sumTax"] == "20"


@pytest.mark.parametrize("invoice_date,selected_month", [
    ("2026-08-20", 8), ("2026-09-04", 9), ("2026-10-04", 9),
])
def test_acquisition_tax_point_respects_invoice_and_next_month_fifteenth(
    invoice_date: str, selected_month: int,
) -> None:
    document = {
        "id": "acquisition", "status": "150", "voucherDate": invoice_date,
        "deliveryDate": "2026-08-24", "sumNet": "100", "sumTax": "0",
        "sumGross": "100", "taxText": "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)",
    }
    selector = UvaDocumentSelector()
    for month in (8, 9, 10):
        result = selector.select_purchase_documents(2026, month, [document])
        assert bool(result.documents) == (month == selected_month)


def test_incoming_rc_draft_is_not_taxable() -> None:
    result = UvaDocumentSelector().select_purchase_documents(2026, 9, [{
        "id": "draft", "status": "50", "voucherDate": "2026-09-04",
        "sumNet": "100", "taxText": "REVERSE CHARGE",
    }])
    assert result.documents == []
    assert result.stats.draft_or_open_ignored == 1


def test_rc_advance_in_different_month_blocks_tax_submission() -> None:
    from xw_office.services.finanzonline.client import FinanzOnlineClient
    from xw_office.services.finanzonline.uva_service import UvaService, build_data_quality
    from xw_office.services.finanzonline.uva_soap import MockUvaSoapBackend

    selected = UvaDocumentSelector().select_purchase_documents(2026, 9, [{
        "id": "advance", "status": "1000", "voucherDate": "2026-09-04",
        "deliveryDate": "2026-09-04", "paidDate": "2026-08-04",
        "sumNet": "100", "sumGross": "100", "taxText": "REVERSE CHARGE",
    }])
    quality = build_data_quality({"warnings": selected.warnings})
    backend = MockUvaSoapBackend()
    service = UvaService(AppConfig(), FinanzOnlineClient(AppConfig(), uva_backend=backend))
    service._calculation_cache[(2026, 9)] = {"data_quality": quality}
    result = service.submit_uva_month(2026, 9)
    assert not result.ok
    assert "Steuerperiode" in result.message
    assert backend.calls == []


def test_malformed_bulk_history_cannot_claim_complete_payment_evidence() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        rows = [{"id": "invalid"}] if request.url.path == "/CheckAccountTransactionLog" else [{
            "id": "assignment", "assignedAmount": "60", "bookingDate": "2026-09-04",
        }]
        return httpx.Response(200, json={"objects": rows})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        provider.prepare_payment_logs()
        assert not provider._payment_evidence.complete
        _, amount = provider._load_payment_metadata(
            "Invoice", "1", 2026, 9, expected_paid_amount=Decimal("60")
        )
    assert amount == "60.00"
    assert calls == ["/CheckAccountTransactionLog", "/Invoice/1/getCheckAccountTransactionLogs"]


@pytest.mark.parametrize("response", ["unavailable", "empty"])
def test_tax_set_lookup_failure_cannot_silently_change_classification(response: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503 if response == "unavailable" else 200, json={"objects": []})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        with pytest.raises((SevdeskApiError, ValueError)):
            provider._fetch_tax_set_text("missing")
        assert "missing" not in provider._tax_set_text_cache


def test_historical_overlay_includes_late_bookkeeping_corrections() -> None:
    bounds: list[int] = []
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    def handler(request: httpx.Request) -> httpx.Response:
        bounds.append(int(request.url.params["updateBefore"]))
        return httpx.Response(200, json={"objects": []})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskUvaPreviewProvider(SevdeskConnection(client, AppConfig()))
        provider._load_period_overlay("Voucher", 2020, 1, statuses=None)
    assert bounds[0] >= int(today_start.timestamp())


def test_document_without_id_cannot_silently_disappear_from_calculation() -> None:
    with pytest.raises(ValueError, match="eindeutige ID"):
        SevdeskUvaPreviewProvider._merge_documents([{"sumNet": "100"}])


@pytest.mark.parametrize("domestic", [False, True])
def test_zm_preserves_free_positions_and_excludes_domestic_rc(domestic: bool) -> None:
    from xw_office.services.finanzonline.zm_service import SevdeskZmInvoiceProvider, ZmService

    def handler(request: httpx.Request) -> httpx.Response:
        rows = [{
            "id": "zm-invoice", "status": "200", "invoiceDate": "2026-09-04",
            "contact": {"name": "Customer", "vatNumber": "ATU12345678" if domestic else "DE136695976"},
            "taxText": "REVERSE CHARGE" if domestic else "INNERGEMEINSCHAFTLICHE LIEFERUNG",
            "sumNetAccounting": "10",
            "xw_positions": [
                {"sumNetAccounting": "10"},
                {"sumNetAccounting": "0", "price": "5", "quantity": "1", "discount": "100"},
            ],
        }] if request.url.path == "/Invoice" else []
        return httpx.Response(200, json={"objects": rows})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        result = ZmService(SevdeskZmInvoiceProvider(SevdeskConnection(client, AppConfig()))).calculate_month(2026, 9)
    assert result.invalid == []
    if domestic:
        assert result.rows == []
    else:
        assert len(result.rows) == 1
        assert result.rows[0].amount_eur_int == 10


def test_zm_document_page_limit_does_not_return_partial_month() -> None:
    from xw_office.services.finanzonline.zm_service import SevdeskZmInvoiceProvider

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"objects": [{"id": "one"}, {"id": "two"}]})
        ), base_url="https://example.test",
    ) as client:
        provider = SevdeskZmInvoiceProvider(
            SevdeskConnection(client, AppConfig()), page_size=2, max_pages=1,
        )
        with pytest.raises(RuntimeError, match="nicht vollstaendig"):
            provider.load_invoices(2026, 9)
