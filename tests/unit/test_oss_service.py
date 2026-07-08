from __future__ import annotations

import pytest

from xw_studio.services.finanzonline.oss_service import OssService


class _QuarterProvider:
    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, object]]:
        assert (year, quarter) == (2026, 1)
        return [
            {
                "id": 1,
                "invoiceNumber": "RE-DE-1",
                "invoiceDate": "2026-01-31",
                "deliveryDate": "2026-02-14",
                "taxText": "Deutsche MwSt. 19%",
                "sumNet": "100.00",
                "sumTax": "19.00",
            },
            {
                "id": 2,
                "invoiceNumber": "RE-FR-1",
                "invoiceDate": "2026-03-01",
                "deliveryDate": "2026-03-02",
                "addressCountryCode": "FR",
                "taxText": "Franzoesische TVA 20%",
                "sumNet": "50.00",
                "sumTax": "10.00",
                "xw_oss_goods": False,
            },
            {
                "id": 3,
                "invoiceNumber": "RE-RC-1",
                "invoiceDate": "2026-03-10",
                "deliveryDate": "2026-03-10",
                "addressCountryCode": "DE",
                "taxText": "Reverse Charge EU",
                "sumNet": "70.00",
                "sumTax": "0.00",
                "taxRule": {"id": "5"},
            },
            {
                "id": 4,
                "invoiceNumber": "RE-AT-1",
                "invoiceDate": "2026-03-15",
                "deliveryDate": "2026-03-15",
                "addressCountryCode": "AT",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumNet": "120.00",
                "sumTax": "24.00",
            },
            {
                "id": 5,
                "invoiceNumber": "RE-DE-Q2",
                "invoiceDate": "2026-03-31",
                "deliveryDate": "2026-04-02",
                "addressCountryCode": "DE",
                "taxText": "Deutsche MwSt. 7%",
                "sumNet": "30.00",
                "sumTax": "2.10",
            },
        ]


class _ZeroTaxTextProvider:
    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, object]]:
        assert (year, quarter) == (2026, 1)
        return [
            {
                "id": 6,
                "invoiceNumber": "RE-PT-1",
                "invoiceDate": "2026-01-18",
                "deliveryDate": "2026-01-18",
                "addressCountryCode": "PT",
                "taxText": "0",
                "sumNet": "100.00",
                "sumTax": "10.00",
                "xw_positions": [
                    {
                        "sumNet": "100.00",
                        "sumTax": "10.00",
                        "taxRate": "10",
                    }
                ],
            }
        ]


class _EmptyProvider:
    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, object]]:
        assert (year, quarter) == (2026, 1)
        return []


class _DomesticMissingCountryProvider:
    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, object]]:
        assert (year, quarter) == (2026, 1)
        return [
            {
                "id": 7,
                "invoiceNumber": "RE-AT-NO-COUNTRY",
                "invoiceDate": "2026-02-10",
                "deliveryDate": "2026-02-10",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumNet": "100.00",
                "sumTax": "20.00",
            }
        ]


def test_oss_service_collects_foreign_b2c_sales_by_delivery_quarter() -> None:
    service = OssService(_QuarterProvider())

    result = service.calculate_quarter(2026, 1)

    assert len(result.goods_lines) == 1
    assert len(result.service_lines) == 1
    assert result.goods_lines[0].country_code == "DE"
    assert result.goods_lines[0].vat_rate == "19.00"
    assert result.goods_lines[0].taxable_amount == "100.00"
    assert result.service_lines[0].country_code == "FR"
    assert result.service_lines[0].goods is False
    assert result.service_lines[0].tax_amount == "10.00"
    assert all("Nullquartal" not in warning for warning in result.warnings)


def test_oss_service_uses_zero_taxtext_with_country_and_rate_as_candidate() -> None:
    service = OssService(_ZeroTaxTextProvider())

    result = service.calculate_quarter(2026, 1)

    assert len(result.goods_lines) == 1
    assert result.goods_lines[0].country_code == "PT"
    assert result.goods_lines[0].vat_rate == "10.00"
    assert result.goods_lines[0].taxable_amount == "100.00"


def test_oss_xml_export_contains_expected_fields() -> None:
    service = OssService(_QuarterProvider())

    export = service.build_xml_export(2026, 1, oss_id="ATU73931409")

    assert export.file_name == "EU-OSS_2026_Q1.xml"
    assert "<OSSReturn>" in export.xml_payload
    assert "<ossId>ATU73931409</ossId>" in export.xml_payload
    assert "<countryCode>DE</countryCode>" in export.xml_payload
    assert "<goods>true</goods>" in export.xml_payload
    assert "<taxable>100,00</taxable>" in export.xml_payload
    assert "<vatRate>19,00</vatRate>" in export.xml_payload


def test_oss_xml_export_blocks_null_quarter() -> None:
    service = OssService(_EmptyProvider())

    with pytest.raises(ValueError, match="Nullmeldung"):
        service.build_xml_export(2026, 1, oss_id="ATU73931409")


def test_oss_service_does_not_warn_about_missing_country_for_non_oss_invoice() -> None:
    service = OssService(_DomesticMissingCountryProvider())

    result = service.calculate_quarter(2026, 1)

    assert result.goods_lines == []
    assert result.service_lines == []
    assert all("Land unklar" not in warning for warning in result.warnings)