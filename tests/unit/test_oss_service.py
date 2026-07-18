from __future__ import annotations

import threading
import time

import pytest

from xw_studio.services.finanzonline.oss_models import OssLine, OssQuarterResult
from xw_studio.services.finanzonline.oss_references import compare_oss_reference, load_oss_references
from xw_studio.services.finanzonline.oss_service import (
    OssService,
    SevdeskOssDocumentProvider,
    build_oss_xml,
    validate_oss_xml,
)
from xw_studio.services.finanzonline.oss_snapshot import OssQuarterSnapshotStore


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
                "taxText": "Franzoesische TVA 5,5%",
                "sumNet": "50.00",
                "sumTax": "2.75",
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
                "invoiceNumber": "RE-ES-1",
                "invoiceDate": "2026-01-18",
                "deliveryDate": "2026-01-18",
                "addressCountryCode": "ES",
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


class _KnownZeroRateProvider:
    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, object]]:
        assert (year, quarter) == (2026, 2)
        return [
            {
                "id": 8,
                "invoiceNumber": "RE-CZ-OK",
                "invoiceDate": "2026-05-18",
                "deliveryDate": "2026-05-18",
                "taxText": "Tschechische DPH 0% (seit 2024)",
                "sumNet": "34.80",
                "sumTax": "0.00",
            }
        ]


class _ConflictingZeroRateProvider:
    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, object]]:
        assert (year, quarter) == (2026, 2)
        return [
            {
                "id": 9,
                "invoiceNumber": "RE-CZ-CONFLICT",
                "invoiceDate": "2026-05-18",
                "deliveryDate": "2026-05-18",
                "taxText": "Tschechische DPH 0% (seit 2024)",
                "sumNet": "32.26",
                "sumTax": "2.54",
            }
        ]


class _DocumentFallbackProvider:
    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, object]]:
        assert (year, quarter) == (2026, 1)
        return [
            {
                "id": 10,
                "invoiceNumber": "RE-LU-FALLBACK",
                "invoiceDate": "2026-02-20",
                "deliveryDate": "2026-02-20",
                "taxText": "Luxemburgische TVA 3%",
                "sumNet": "30.87",
                "sumTax": "0.93",
                "xw_positions": [
                    {
                        "sumNet": "0.00",
                        "sumTax": "0.00",
                        "taxText": "Luxemburgische TVA 3%",
                    }
                ],
            }
        ]


class _UnknownForeignRuleProvider:
    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, object]]:
        assert (year, quarter) == (2026, 1)
        return [
            {
                "id": 11,
                "invoiceNumber": "RE-UNKNOWN-RULE",
                "invoiceDate": "2026-02-20",
                "deliveryDate": "2026-02-20",
                "addressCountryCode": "PL",
                "taxText": "Polnische VAT 5%",
                "sumNet": "100.00",
                "sumTax": "5.00",
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


class _ParallelPositionProvider(SevdeskOssDocumentProvider):
    def __init__(self) -> None:
        super().__init__(connection=None, max_position_workers=3)  # type: ignore[arg-type]
        self._active = 0
        self.max_active = 0
        self._active_lock = threading.Lock()

    def _load_resource(self, path: str, *, params: dict[str, object] | None = None) -> list[dict[str, object]]:
        if path == "/Invoice":
            return [{"id": str(index), "invoiceNumber": f"RE-{index}"} for index in range(6)]
        return []


    def _load_positions(self, resource: str, doc_id: str) -> list[dict[str, object]]:
        with self._active_lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(0.02)
            return [{"id": f"POS-{doc_id}", "sumNet": "1.00"}]
        finally:
            with self._active_lock:
                self._active -= 1


class _CountingQuarterProvider(_QuarterProvider):
    def __init__(self) -> None:
        self.calls = 0

    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, object]]:
        self.calls += 1
        return super().load_sales_documents(year, quarter)


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
    assert result.service_lines[0].tax_amount == "2.75"
    assert all("Nullquartal" not in warning for warning in result.warnings)


def test_oss_service_uses_zero_taxtext_with_known_country_rate_as_candidate() -> None:
    service = OssService(_ZeroTaxTextProvider())

    result = service.calculate_quarter(2026, 1)

    assert len(result.goods_lines) == 1
    assert result.goods_lines[0].country_code == "ES"
    assert result.goods_lines[0].vat_rate == "10.00"
    assert result.goods_lines[0].taxable_amount == "100.00"


def test_oss_service_accepts_known_zero_percent_rule_without_tax_amount() -> None:
    service = OssService(_KnownZeroRateProvider())

    result = service.calculate_quarter(2026, 2)

    assert len(result.goods_lines) == 1
    assert result.goods_lines[0].country_code == "CZ"
    assert result.goods_lines[0].vat_rate == "0.00"
    assert result.goods_lines[0].taxable_amount == "34.80"
    assert result.goods_lines[0].tax_amount == "0.00"


def test_oss_service_blocks_zero_percent_rule_with_positive_tax_amount() -> None:
    service = OssService(_ConflictingZeroRateProvider())

    result = service.calculate_quarter(2026, 2)

    assert result.goods_lines == []
    assert any("0 %, aber Steuerbetrag 2.54 EUR" in warning for warning in result.warnings)


def test_oss_service_uses_document_header_when_positions_are_incomplete() -> None:
    service = OssService(_DocumentFallbackProvider())

    result = service.calculate_quarter(2026, 1)

    assert len(result.goods_lines) == 1
    assert result.goods_lines[0].country_code == "LU"
    assert result.goods_lines[0].taxable_amount == "30.87"
    assert result.goods_lines[0].tax_amount == "0.93"
    assert any("Dokumentkopf genutzt" in warning for warning in result.warnings)


def test_oss_service_warns_and_excludes_unknown_foreign_tax_rule() -> None:
    service = OssService(_UnknownForeignRuleProvider())

    result = service.calculate_quarter(2026, 1)

    assert result.goods_lines == []
    assert any("unbekannte sevDesk-USt-Regel" in warning for warning in result.warnings)


def test_oss_xml_export_contains_expected_fields() -> None:
    service = OssService(_QuarterProvider())

    export = service.build_xml_export(2026, 1, oss_id="ATU73931409")

    assert export.file_name == "EU-OSS_2026_Q1.xml"
    assert "<Erklaerungen>" in export.xml_payload
    assert "<mscon>DE</mscon>" in export.xml_payload
    assert "<goods>true</goods>" in export.xml_payload
    assert "<taxable>100,00</taxable>" in export.xml_payload
    assert "<vatRate>19,00</vatRate>" in export.xml_payload
    assert "<taxamount>" not in export.xml_payload


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


def test_oss_references_are_loaded_as_immutable_mapping() -> None:
    references = load_oss_references()

    assert references["2026-Q2"]["lines"][-1]["country_code"] == "CZ"
    assert references["2026-Q2"]["lines"][-1]["vat"] == "0.00"
    try:
        references["2026-Q2"] = {}  # type: ignore[index]
    except TypeError:
        pass
    else:  # pragma: no cover - defensive assertion.
        raise AssertionError("Reference mapping must be immutable")


def test_oss_reference_comparison_reports_deltas_without_overriding() -> None:
    result = OssQuarterResult(
        year=2026,
        quarter=2,
        goods_lines=[
            OssLine(
                country_code="CZ",
                country_name="Czechia",
                vat_rate="0.00",
                taxable_amount="34.80",
                tax_amount="0.00",
            ),
            OssLine(
                country_code="DE",
                country_name="Germany",
                vat_rate="7.00",
                taxable_amount="4004.51",
                tax_amount="284.79",
            ),
        ],
    )

    comparison = compare_oss_reference(result)
    rows = {(row["country_code"], row["vat_rate"]): row for row in comparison["lines"]}

    assert comparison["available"] is True
    assert rows[("CZ", "0.00")]["within_tolerance"] is True
    assert rows[("DE", "7.00")]["delta_net"] == "-31.75"
    assert comparison["within_tolerance"] is False


def test_sevdesk_oss_provider_loads_positions_with_bounded_parallelism() -> None:
    provider = _ParallelPositionProvider()

    documents = provider.load_sales_documents(2026, 1)

    assert len(documents) == 6
    assert provider.max_active > 1
    assert provider.max_active <= 3
    assert all(document["xw_positions"] for document in documents)


def test_oss_service_reuses_persistent_quarter_snapshot(tmp_path) -> None:
    store = OssQuarterSnapshotStore(tmp_path / "tax.sqlite")
    first_provider = _CountingQuarterProvider()
    first_service = OssService(first_provider, snapshot_store=store)

    first = first_service.calculate_quarter(2026, 1)

    second_provider = _CountingQuarterProvider()
    second_service = OssService(second_provider, snapshot_store=store)
    second = second_service.calculate_quarter(2026, 1)

    assert first.cache["source"] == "live"
    assert second.cache["source"] == "persistent"
    assert second_provider.calls == 0
    assert second.goods_lines[0].taxable_amount == "100.00"
    assert second.cache["snapshot_hash"] == first.cache["snapshot_hash"]


def test_oss_service_refresh_bypasses_persistent_snapshot(tmp_path) -> None:
    store = OssQuarterSnapshotStore(tmp_path / "tax.sqlite")
    provider = _CountingQuarterProvider()
    service = OssService(provider, snapshot_store=store)

    service.calculate_quarter(2026, 1)
    refreshed = service.calculate_quarter(2026, 1, refresh=True)

    assert refreshed.cache["source"] == "live"
    assert provider.calls == 2


def test_oss_xml_validation_blocks_duplicate_country_rate_type() -> None:
    result = OssQuarterResult(
        year=2026,
        quarter=1,
        goods_lines=[
            OssLine(
                country_code="DE",
                country_name="Germany",
                vat_rate="7.00",
                taxable_amount="100.00",
                tax_amount="7.00",
            ),
            OssLine(
                country_code="DE",
                country_name="Germany",
                vat_rate="7.00",
                taxable_amount="50.00",
                tax_amount="3.50",
            ),
        ],
    )

    with pytest.raises(ValueError, match="doppelte Zeile"):
        validate_oss_xml(build_oss_xml(result, oss_id="ATU73931409"))


def test_oss_xml_export_skips_zero_percent_lines_with_warning() -> None:
    service = OssService(_KnownZeroRateProvider())

    with pytest.raises(ValueError, match="0%-Zeilen"):
        service.build_xml_export(2026, 2, oss_id="ATU73931409")

    mixed = OssQuarterResult(
        year=2026,
        quarter=2,
        goods_lines=[
            OssLine(
                country_code="CZ",
                country_name="Czechia",
                vat_rate="0.00",
                taxable_amount="34.80",
                tax_amount="0.00",
            ),
            OssLine(
                country_code="DE",
                country_name="Germany",
                vat_rate="7.00",
                taxable_amount="100.00",
                tax_amount="7.00",
            ),
        ],
    )

    export = service.build_xml_export_from_result(mixed)

    assert "<mscon>DE</mscon>" in export.xml_payload
    assert "<mscon>CZ</mscon>" not in export.xml_payload
    assert export.line_count == 1
    assert any("0%-Zeilen" in warning for warning in export.warnings)
