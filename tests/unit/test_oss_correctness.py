from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pytest

from xw_office.core.config import AppConfig
from xw_office.core.exceptions import SevdeskApiError
from xw_office.services.finanzonline.oss_service import OssService, SevdeskOssDocumentProvider
from xw_office.services.http_client import SevdeskConnection


class Documents:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, Any]]:
        return self.documents


def invoice(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "one", "invoiceDate": "2026-08-04", "deliveryDate": "2026-08-04",
        "status": "200", "taxText": "Deutsche MwSt. 7%", "sumNet": "100",
        "sumTax": "7", **overrides,
    }


def test_discount_accounting_header_is_authoritative() -> None:
    result = OssService(Documents([invoice(
        sumNetAccounting="90", sumTaxAccounting="6.30",
    )])).calculate_quarter(2026, 3)
    assert result.goods_lines[0].taxable_amount == "90.00"
    assert result.goods_lines[0].tax_amount == "6.30"


def test_free_shipping_is_not_reconstructed_from_undiscounted_price() -> None:
    result = OssService(Documents([invoice(
        sumNet="10", sumTax="0.70", xw_positions=[
            {"sumNetAccounting": "10", "sumTaxAccounting": "0.70"},
            {"sumNetAccounting": "0", "sumTaxAccounting": "0", "price": "5", "quantity": "1"},
        ],
    )])).calculate_quarter(2026, 3)
    assert result.goods_lines[0].taxable_amount == "10.00"
    assert result.goods_lines[0].tax_amount == "0.70"
    assert not result.blocking
    assert not any("Dokumentkopf" in warning for warning in result.warnings)


def test_mixed_rates_are_not_replaced_by_single_header_rate() -> None:
    result = OssService(Documents([invoice(
        sumNet="150", sumTax="16.50",
        xw_positions=[
            {"sumNet": "100", "sumTax": "7", "taxText": "Deutsche MwSt. 7%", "taxRate": "7"},
            {"sumNet": "50", "sumTax": "9.50", "taxText": "Deutsche MwSt. 19%", "taxRate": "19"},
        ],
    )])).calculate_quarter(2026, 3)
    assert {row.vat_rate: row.taxable_amount for row in result.goods_lines} == {
        "7.00": "100.00", "19.00": "50.00",
    }
    assert not result.blocking


def test_duplicates_and_drafts_cannot_inflate_oss() -> None:
    document = invoice()
    result = OssService(Documents([document, dict(document), invoice(id="draft", status="100")])).calculate_quarter(2026, 3)
    assert result.goods_lines[0].taxable_amount == "100.00"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "nonsense"])
def test_invalid_amount_is_not_silent_zero(value: str) -> None:
    with pytest.raises(ValueError):
        OssService(Documents([invoice(sumNet=value)])).calculate_quarter(2026, 3)


def test_position_net_discrepancy_blocks_instead_of_hiding_mixed_rates() -> None:
    service = OssService(Documents([invoice(xw_positions=[
        {"sumNet": "25", "sumTax": "1.75", "taxText": "Deutsche MwSt. 7%"},
        {"sumNet": "25", "sumTax": "4.75", "taxText": "Deutsche MwSt. 19%"},
    ])]))
    result = service.calculate_quarter(2026, 3)
    assert result.blocking
    with pytest.raises(ValueError, match="blockiert"):
        service.build_xml_export_from_result(result)


def test_credit_requires_portal_correction_instead_of_silent_current_quarter_netting() -> None:
    service = OssService(Documents([
        invoice(),
        invoice(id="credit", xw_doc_type="credit", creditNoteDate="2026-08-20",
                refSrcInvoice={"id": "old"}, sumNet="20", sumTax="1.40"),
    ]))
    result = service.calculate_quarter(2026, 3)
    assert any("Korrektur" in warning for warning in result.blocking)
    with pytest.raises(ValueError, match="blockiert"):
        service.build_xml_export_from_result(result)


def test_bulk_page_limit_and_malformed_rows_fail_explicitly() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"objects": [{"id": "1"}]})),
        base_url="https://example.test",
    ) as client:
        provider = SevdeskOssDocumentProvider(
            SevdeskConnection(client, AppConfig()), page_size=1, max_pages=1,
        )
        with pytest.raises(RuntimeError, match="vollstaendig"):
            provider._load_resource("/Invoice")


def test_live_recalculation_clears_position_cache() -> None:
    value = {"net": "100"}

    def handler(request: httpx.Request) -> httpx.Response:
        rows = [invoice()] if request.url.path == "/Invoice" else []
        if request.url.path == "/InvoicePos":
            rows = [{"sumNet": value["net"], "sumTax": "7"}]
        return httpx.Response(200, json={"objects": rows})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskOssDocumentProvider(SevdeskConnection(client, AppConfig()))
        first = provider.load_sales_documents(2026, 3)
        value["net"] = "200"
        refreshed = provider.load_sales_documents(2026, 3)
    assert first[0]["xw_positions"][0]["sumNet"] == "100"
    assert refreshed[0]["xw_positions"][0]["sumNet"] == "200"


def test_position_api_failure_is_not_disguised_as_header_only_success() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(403, json={"objects": []})),
        base_url="https://example.test",
    ) as client:
        provider = SevdeskOssDocumentProvider(SevdeskConnection(client, AppConfig()))
        with pytest.raises(SevdeskApiError):
            provider._load_positions("Invoice", "one")


def test_explicit_zero_position_tax_is_not_invented_from_the_rate() -> None:
    service = OssService(Documents([invoice(
        sumTax="0", xw_positions=[{"sumNet": "100", "sumTax": "0", "taxRate": "7"}],
    )]))
    result = service.calculate_quarter(2026, 3)
    assert result.goods_lines == []
    assert any("Steuerbetrag" in warning for warning in result.blocking)


def test_destination_conflict_and_unknown_foreign_rule_block_export() -> None:
    service = OssService(Documents([
        invoice(addressCountryCode="FR"),
        invoice(id="unknown", taxText="Polnische VAT 5%", sumTax="5", addressCountryCode="PL"),
    ]))
    result = service.calculate_quarter(2026, 3)
    assert len(result.blocking) == 2
    with pytest.raises(ValueError, match="blockiert"):
        service.build_xml_export_from_result(result)


def test_large_partial_position_page_is_not_truncated() -> None:
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        rows = [{"id": "1"}, {"id": "2"}] if offset == 0 else [{"id": "3"}]
        return httpx.Response(200, json={"objects": rows})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskOssDocumentProvider(SevdeskConnection(client, AppConfig()), page_size=2)
        assert len(provider._load_positions("Invoice", "one")) == 3
    assert offsets == [0, 2]


def test_irrelevant_delivery_periods_do_not_load_positions() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        rows = [invoice(deliveryDate="2026-10-01")] if request.url.path == "/Invoice" else []
        return httpx.Response(200, json={"objects": rows})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        provider = SevdeskOssDocumentProvider(SevdeskConnection(client, AppConfig()))
        docs = provider.load_sales_documents(2026, 3)
    assert len(docs) == 1
    assert calls == ["/Invoice", "/CreditNote"]


def test_small_single_rate_rounding_difference_uses_header_amounts() -> None:
    result = OssService(Documents([invoice(
        xw_positions=[
            {"sumNet": "33.33", "sumTax": "2.33", "taxRate": "7"} for _ in range(3)
        ],
    )])).calculate_quarter(2026, 3)
    assert result.goods_lines[0].taxable_amount == "100.00"
    assert result.goods_lines[0].tax_amount == "7.00"
    assert not result.blocking


def test_malformed_source_rows_cannot_turn_into_null_quarter() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"objects": [None]})),
        base_url="https://example.test",
    ) as client:
        provider = SevdeskOssDocumentProvider(SevdeskConnection(client, AppConfig()))
        with pytest.raises(ValueError, match="Objektliste"):
            provider._load_resource("/Invoice")


@pytest.mark.parametrize("delivery_date", [
    "04.08.2026", str(int(datetime(2026, 8, 4).timestamp())), "2026-08-04T12:00:00+02:00",
])
def test_shared_date_parser_preserves_delivery_quarter(delivery_date: str) -> None:
    result = OssService(Documents([invoice(deliveryDate=delivery_date)])).calculate_quarter(2026, 3)
    assert result.goods_lines[0].taxable_amount == "100.00"


def test_missing_source_configuration_is_not_a_null_quarter() -> None:
    with pytest.raises(RuntimeError, match="Datenquelle"):
        OssService().calculate_quarter(2026, 3)


def test_missing_rule_text_cannot_hide_inconsistent_foreign_tax() -> None:
    result = OssService(Documents([invoice(
        taxText="0", addressCountryCode="DE", taxRate="7", sumTax="0",
    )])).calculate_quarter(2026, 3)
    assert result.blocking
    assert result.goods_lines == []


def test_multiple_consumption_countries_are_not_merged_into_first_country() -> None:
    result = OssService(Documents([invoice(
        sumNet="200", sumTax="11",
        xw_positions=[
            {"sumNet": "100", "sumTax": "7", "taxText": "Deutsche MwSt. 7%"},
            {"sumNet": "100", "sumTax": "4", "taxText": "Italienische IVA 4%"},
        ],
    )])).calculate_quarter(2026, 3)
    assert result.goods_lines == []
    assert any("Verbrauchslaender" in warning for warning in result.blocking)
