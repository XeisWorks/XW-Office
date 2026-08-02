from __future__ import annotations

import json
from pathlib import Path

from xw_office.services.finanzonline.uva_payload_service import UvaPayloadService
from xw_office.services.finanzonline.uva_preview import SevdeskUvaPreviewProvider, UvaPreviewService
from xw_office.services.finanzonline.uva_references import (
    compare_uva_reference,
    load_uva_references,
)


class _FakeProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "taxText": "MIT 0% MEHRWERTSTEUER",
                "sumGross": "80.87",
                "sumNet": "80.87",
                "sumTax": "0.00",
            },
            {
                "taxText": "MIT 10% MEHRWERTSTEUER",
                "sumGross": "7909.60",
                "sumNet": "7191.06",
                "sumTax": "718.54",
            },
            {
                "taxText": "MIT 13% MEHRWERTSTEUER",
                "sumGross": "1793.73",
                "sumNet": "1587.37",
                "sumTax": "206.36",
            },
            {
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "69.39",
                "sumNet": "57.83",
                "sumTax": "11.56",
            },
            {
                "taxText": "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)",
                "sumGross": "4825.18",
                "sumNet": "4825.18",
                "sumTax": "0.00",
            },
            {
                "taxText": "REVERSE CHARGE",
                "sumGross": "122.83",
                "sumNet": "122.83",
                "sumTax": "0.00",
            },
            {
                "taxText": "DEUTSCHE MWST. 7%",
                "sumGross": "2438.60",
                "sumNet": "2272.96",
                "sumTax": "165.64",
            },
            {
                "taxText": "ITALIENISCHE IVA 4%",
                "sumGross": "114.90",
                "sumNet": "110.47",
                "sumTax": "4.43",
            },
            {
                "taxText": "STEUERFREIE AUSFUHRLIEFERUNG (§ 7 USTG 1994)",
                "sumGross": "865.13",
                "sumNet": "865.13",
                "sumTax": "0.00",
            },
            {
                "taxText": "LUXEMBURGISCHE TVA 3%",
                "sumGross": "31.80",
                "sumNet": "30.87",
                "sumTax": "0.93",
            },
            {
                "taxText": "SCHWEDISCHE MOMS 6%",
                "sumGross": "24.80",
                "sumNet": "20.83",
                "sumTax": "3.97",
            },
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "taxText": "MIT 0% MEHRWERTSTEUER",
                "sumGross": "2446.99",
                "sumNet": "2446.99",
                "sumTax": "0.00",
            },
            {
                "taxText": "MIT 10% MEHRWERTSTEUER",
                "sumGross": "1384.93",
                "sumNet": "1259.03",
                "sumTax": "125.90",
            },
            {
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "1048.11",
                "sumNet": "873.43",
                "sumTax": "174.68",
            },
            {
                "taxText": "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)",
                "sumGross": "76.62",
                "sumNet": "76.62",
                "sumTax": "0.00",
            },
            {
                "taxText": "REVERSE CHARGE",
                "sumGross": "650.82",
                "sumNet": "650.82",
                "sumTax": "0.00",
            },
        ]


class _FebruaryProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 2)
        return [
            {
                "taxText": "MIT 10% MEHRWERTSTEUER",
                "sumGross": "4173.31",
                "sumNet": "3794.34",
                "sumTax": "378.97",
            },
            {
                "taxText": "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)",
                "sumGross": "3346.20",
                "sumNet": "3346.20",
                "sumTax": "0.00",
            },
            {
                "taxText": "REVERSE CHARGE",
                "sumGross": "134.00",
                "sumNet": "134.00",
                "sumTax": "0.00",
            },
            {
                "taxText": "DEUTSCHE MWST. 7%",
                "sumGross": "1480.97",
                "sumNet": "1380.21",
                "sumTax": "100.76",
            },
            {
                "taxText": "ITALIENISCHE IVA 4%",
                "sumGross": "264.10",
                "sumNet": "253.90",
                "sumTax": "10.20",
            },
            {
                "taxText": "STEUERFREIE AUSFUHRLIEFERUNG (Â§ 7 USTG 1994)",
                "sumGross": "185.30",
                "sumNet": "185.30",
                "sumTax": "0.00",
            },
            {
                "taxText": "LUXEMBURGISCHE TVA 3%",
                "sumGross": "63.60",
                "sumNet": "61.74",
                "sumTax": "1.86",
            },
            {
                "taxText": "SPANISCHE IVA 10%",
                "sumGross": "5.50",
                "sumNet": "5.00",
                "sumTax": "0.50",
            },
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 2)
        return [
            {
                "taxText": "MIT 0% MEHRWERTSTEUER",
                "sumGross": "4232.91",
                "sumNet": "4232.91",
                "sumTax": "0.00",
            },
            {
                "taxText": "MIT 10% MEHRWERTSTEUER",
                "sumGross": "308.43",
                "sumNet": "280.39",
                "sumTax": "28.04",
            },
            {
                "taxText": "MIT 13% MEHRWERTSTEUER",
                "sumGross": "1130.00",
                "sumNet": "1000.00",
                "sumTax": "130.00",
            },
            {
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "4008.93",
                "sumNet": "3340.78",
                "sumTax": "668.15",
            },
            {
                "taxText": "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)",
                "sumGross": "5917.67",
                "sumNet": "5917.67",
                "sumTax": "0.00",
            },
            {
                "taxText": "REVERSE CHARGE",
                "sumGross": "2077.90",
                "sumNet": "2077.90",
                "sumTax": "0.00",
            },
        ]


def test_phase1_preview_matches_expected_fixture() -> None:
    service = UvaPreviewService(_FakeProvider())
    preview = service.build_preview(2026, 3)
    rendered = service.render_preview_text(preview)

    fixture = Path(__file__).resolve().parents[1] / "expected" / "UVA 03-26.txt"
    expected = fixture.read_text(encoding="utf-8").strip()

    assert rendered.strip() == expected


def test_phase1_preview_matches_february_expected_values() -> None:
    service = UvaPreviewService(_FebruaryProvider())
    preview = service.build_preview(2026, 2)
    rendered = service.render_preview_text(preview)

    fixture = Path(__file__).resolve().parents[1] / "expected" / "UVA 02-26.txt"
    expected = fixture.read_text(encoding="utf-8").strip()

    assert _semantic_preview_lines(rendered) == _semantic_preview_lines(expected)


def test_phase1_payload_contains_preview_text() -> None:
    service = UvaPreviewService(_FakeProvider())
    preview = service.build_preview(2026, 3)

    assert preview.sales.total_vat == "1111.43"
    assert preview.input_tax.total_vat == "300.58"
    assert len(preview.sales.groups) == 11


def test_phase2_builds_expected_kennzahlen() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_FakeProvider()))
    payload = payload_service.build_payload(2026, 3)

    assert payload.rule_version == "U30_01_2022"
    assert payload.kennzahlen.A000 == "14649.40"
    assert payload.kennzahlen.A017 == "4825.18"
    assert payload.kennzahlen.A021 == "122.83"
    assert payload.kennzahlen.A011 == "865.13"
    assert payload.kennzahlen.A022 == "57.83"
    assert payload.kennzahlen.A029 == "7191.06"
    assert payload.kennzahlen.A006 == "1587.37"
    assert payload.kennzahlen.A057 == "130.16"
    assert payload.kennzahlen.B070 == "76.62"
    assert payload.kennzahlen.B072 == "76.62"
    assert payload.kennzahlen.C060 == "300.58"
    assert payload.kennzahlen.C065 == "15.32"
    assert payload.kennzahlen.C066 == "130.16"


def test_phase2_uses_july_2026_rule_version() -> None:
    class _JulyProvider(_FakeProvider):
        def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
            assert (year, month) == (2026, 7)
            return []

        def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
            assert (year, month) == (2026, 7)
            return []

    payload = UvaPayloadService(UvaPreviewService(_JulyProvider())).build_payload(2026, 7)

    assert payload.rule_version == "U30_07_2026"


def test_phase2_kennzahlen_text_mentions_zahllast() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_FakeProvider()))
    payload = payload_service.build_payload(2026, 3)
    text = payload_service.render_kennzahlen_text(payload)

    assert "A022" in text
    assert "C060" in text
    assert "Zahllast" in text


class _CashBasisSelectionProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 1,
                "invoiceNumber": "RE-1",
                "status": "1000",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "paidDate": "2026-03-05",
            },
            {
                "id": 2,
                "invoiceNumber": "RE-2",
                "status": "1000",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "invoiceDate": "2026-03-06",
                "paidDate": "2026-04-02",
            },
            {
                "id": 3,
                "invoiceNumber": "RE-3",
                "status": "300",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "paidDate": "2026-03-15",
                "paidAmount": "60.00",
            },
            {
                "id": 4,
                "invoiceNumber": "RE-4",
                "status": "cancelled",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "invoiceDate": "2026-03-18",
                "cancelled": True,
            },
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 10,
                "voucherNumber": "ER-100",
                "supplierNameAtSave": "Supplier GmbH",
                "status": "paid",
                "creditDebit": "C",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "payDate": "2026-03-07",
            },
            {
                "id": 11,
                "voucherNumber": "ER-100",
                "supplierNameAtSave": "Supplier GmbH",
                "status": "paid",
                "creditDebit": "C",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "payDate": "2026-03-08",
            },
        ]


def test_phase2_uses_cash_basis_partial_payments_and_dedupes_duplicates() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_CashBasisSelectionProvider()))
    payload = payload_service.build_payload(2026, 3)

    assert payload.kennzahlen.A022 == "150.00"
    assert payload.kennzahlen.C060 == "20.00"
    assert any("storniert" in warning.lower() for warning in payload.warnings)
    assert any("duplik" in warning.lower() for warning in payload.warnings)


class _FutureDatedPurchaseProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        return []

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 5)
        return [
            {
                "id": 12,
                "voucherNumber": "ER-FUTURE-1",
                "status": "1000",
                "creditDebit": "C",
                "voucherDate": "2026-06-02",
                "payDate": "2026-05-30",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "599.00",
                "sumNet": "499.17",
                "sumTax": "99.83",
            }
        ]


def test_future_dated_purchase_is_not_claimed_in_earlier_uva() -> None:
    preview_service = UvaPreviewService(_FutureDatedPurchaseProvider())
    preview = preview_service.build_preview(2026, 5)
    payload = UvaPayloadService(preview_service).build_payload(2026, 5)

    assert payload.kennzahlen.C060 == "0.00"
    assert preview.input_tax_stats.future_document_ignored == 1
    assert any("zukuenftiger eingangsbeleg" in warning.lower() for warning in payload.warnings)


class _PaidWithoutDateProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 200,
                "invoiceNumber": "RE-FALLBACK-1",
                "status": "1000",
                "invoiceDate": "2026-03-10",
                "taxText": "MIT 10% MEHRWERTSTEUER",
                "sumGross": "110.00",
                "sumNet": "100.00",
                "sumTax": "10.00",
            }
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return []


class _PaidWithOverlayDateProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 201,
                "invoiceNumber": "RE-OVERLAY-1",
                "status": "1000",
                "invoiceDate": "2026-02-10",
                "xw_payment_date": "2026-03-12",
                "taxText": "MIT 10% MEHRWERTSTEUER",
                "sumGross": "110.00",
                "sumNet": "100.00",
                "sumTax": "10.00",
            }
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return []


def test_paid_like_document_without_paid_date_is_not_included_without_payment_evidence() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_PaidWithoutDateProvider()))
    payload = payload_service.build_payload(2026, 3)

    assert payload.kennzahlen.A029 == "0.00"
    assert any("zahlungsnachweis" in warning.lower() for warning in payload.warnings)


def test_overlay_payment_date_includes_cash_basis_document() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_PaidWithOverlayDateProvider()))
    payload = payload_service.build_payload(2026, 3)

    assert payload.kennzahlen.A029 == "100.00"


class _UndatedPaidOverlayProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 202,
                "invoiceNumber": "RE-UNDATED-PAID",
                "status": "1000",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
            }
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return []


def test_paid_like_document_without_any_date_is_not_included() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_UndatedPaidOverlayProvider()))
    payload = payload_service.build_payload(2026, 3)

    assert payload.kennzahlen.A022 == "0.00"
    assert any("zahlungsnachweis" in warning.lower() for warning in payload.warnings)


class _LegacyTaxClassificationProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 300,
                "invoiceNumber": "RE-EU-1",
                "status": "1000",
                "invoiceDate": "2026-03-10",
                "xw_payment_date": "2026-03-10",
                "taxType": "eu",
                "sumGross": "250.00",
                "sumNet": "250.00",
                "sumTax": "0.00",
            },
            {
                "id": 301,
                "invoiceNumber": "RE-AT-13",
                "status": "1000",
                "invoiceDate": "2026-03-11",
                "xw_payment_date": "2026-03-11",
                "taxText": "0",
                "sumGross": "113.00",
                "sumNet": "100.00",
                "sumTax": "13.00",
            },
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return []


def test_legacy_tax_metadata_is_mapped_to_expected_uva_groups() -> None:
    preview_service = UvaPreviewService(_LegacyTaxClassificationProvider())
    payload_service = UvaPayloadService(preview_service)

    preview = preview_service.build_preview(2026, 3)
    payload = payload_service.build_payload(2026, 3)
    labels = {group.label for group in preview.sales.groups}

    assert "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)" in labels
    assert "MIT 13% MEHRWERTSTEUER" in labels
    assert payload.kennzahlen.A017 == "250.00"
    assert payload.kennzahlen.A006 == "100.00"


class _MixedPositionProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 400,
                "invoiceNumber": "RE-MIXED-1",
                "status": "1000",
                "xw_payment_date": "2026-03-15",
                "taxText": "0",
                "sumGross": "188.46",
                "sumNet": "167.30",
                "sumTax": "21.16",
                "xw_positions": [
                    {"sumNetAccounting": "150.00", "sumTaxAccounting": "15.00", "taxRate": "10"},
                    {"sumNetAccounting": "17.30", "sumTaxAccounting": "3.46", "taxRate": "20"},
                ],
            }
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return []


def test_preview_splits_mixed_tax_document_by_positions() -> None:
    preview_service = UvaPreviewService(_MixedPositionProvider())
    payload_service = UvaPayloadService(preview_service)

    preview = preview_service.build_preview(2026, 3)
    payload = payload_service.build_payload(2026, 3)
    groups = {group.label: group for group in preview.sales.groups}

    assert groups["MIT 10% MEHRWERTSTEUER"].net_amount == "150.00"
    assert groups["MIT 20% MEHRWERTSTEUER"].net_amount == "17.30"
    assert payload.kennzahlen.A029 == "150.00"
    assert payload.kennzahlen.A022 == "17.30"


class _PartialPaidPositionProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 450,
                "invoiceNumber": "RE-PART-POS",
                "status": "750",
                "xw_payment_date": "2026-03-16",
                "xw_paid_amount": "94.23",
                "taxText": "0",
                "sumGross": "188.46",
                "sumNet": "167.30",
                "sumTax": "21.16",
                "xw_positions": [
                    {"sumNetAccounting": "150.00", "sumTaxAccounting": "15.00", "taxRate": "10"},
                    {"sumNetAccounting": "17.30", "sumTaxAccounting": "3.46", "taxRate": "20"},
                ],
            }
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return []


def test_partial_payment_scales_position_amounts() -> None:
    preview_service = UvaPreviewService(_PartialPaidPositionProvider())
    payload_service = UvaPayloadService(preview_service)

    preview = preview_service.build_preview(2026, 3)
    payload = payload_service.build_payload(2026, 3)
    groups = {group.label: group for group in preview.sales.groups}

    assert groups["MIT 10% MEHRWERTSTEUER"].net_amount == "75.00"
    assert groups["MIT 20% MEHRWERTSTEUER"].net_amount == "8.65"
    assert payload.kennzahlen.A029 == "75.00"
    assert payload.kennzahlen.A022 == "8.65"
    assert any("Teilzahlung" in warning for warning in payload.warnings)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class _PaymentLogConnection:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    def get(self, path: str, params: dict[str, object] | None = None) -> _FakeResponse:
        query = dict(params or {})
        self.requests.append((path, query))
        if path == "/Invoice":
            if "startPayDate" in query:
                return _FakeResponse(
                    {
                        "objects": [
                            {
                                "id": "9001",
                                "status": "750",
                                "invoiceDate": "2026-02-18",
                                "invoiceNumber": "RE-9001",
                                "taxText": "MIT 20% MEHRWERTSTEUER",
                                "sumGross": "120.00",
                                "sumNet": "100.00",
                                "sumTax": "20.00",
                            }
                        ]
                    }
                )
            return _FakeResponse({"objects": []})
        if path == "/Invoice/9001/getCheckAccountTransactionLogs":
            return _FakeResponse(
                {
                    "objects": [
                        {
                            "checkAccountTransaction": {
                                "valueDate": "2026-03-04",
                                "assignedAmountGross": "60.00",
                            }
                        }
                    ]
                }
            )
        if path == "/Invoice/9001/getCheckAccountTransactions":
            return _FakeResponse({"objects": []})
        if path == "/InvoicePos":
            return _FakeResponse({"objects": []})
        if path == "/Voucher":
            return _FakeResponse({"objects": []})
        if path == "/CreditNote":
            return _FakeResponse({"objects": []})
        raise AssertionError(f"Unexpected request: {path} {query}")


def test_provider_uses_payment_logs_before_period_filtering() -> None:
    connection = _PaymentLogConnection()
    provider = SevdeskUvaPreviewProvider(connection)  # type: ignore[arg-type]
    preview_service = UvaPreviewService(provider)
    payload_service = UvaPayloadService(preview_service)

    preview = preview_service.build_preview(2026, 3)
    payload = payload_service.build_payload(2026, 3)

    assert preview.sales.groups[0].net_amount == "50.00"
    assert payload.kennzahlen.A022 == "50.00"
    assert any(
        path == "/Invoice/9001/getCheckAccountTransactionLogs" for path, _ in connection.requests
    )


class _CreditNoteConnection:
    def get(self, path: str, params: dict[str, object] | None = None) -> _FakeResponse:
        query = dict(params or {})
        if path == "/Invoice":
            return _FakeResponse({"objects": []})
        if path == "/Voucher":
            return _FakeResponse({"objects": []})
        if path == "/CreditNote":
            if "startPayDate" in query:
                return _FakeResponse(
                    {
                        "objects": [
                            {
                                "id": "9100",
                                "status": "1000",
                                "creditNoteDate": "2026-03-02",
                                "paidDate": "2026-03-05",
                                "creditNoteNumber": "GU-9100",
                                "refSrcInvoice": {"id": "9000"},
                                "taxText": "MIT 10% MEHRWERTSTEUER",
                                "sumGross": "110.00",
                                "sumNet": "100.00",
                                "sumTax": "10.00",
                            }
                        ]
                    }
                )
            return _FakeResponse({"objects": []})
        if path == "/CreditNotePos":
            return _FakeResponse({"objects": []})
        raise AssertionError(f"Unexpected request: {path} {query}")


class _PaymentLogDuplicateTxConnection:
    def get(self, path: str, params: dict[str, object] | None = None) -> _FakeResponse:
        query = dict(params or {})
        if path == "/Invoice":
            if "startPayDate" in query:
                return _FakeResponse(
                    {
                        "objects": [
                            {
                                "id": "9002",
                                "status": "750",
                                "invoiceDate": "2026-02-20",
                                "invoiceNumber": "RE-9002",
                                "taxText": "MIT 20% MEHRWERTSTEUER",
                                "sumGross": "120.00",
                                "sumNet": "100.00",
                                "sumTax": "20.00",
                            }
                        ]
                    }
                )
            return _FakeResponse({"objects": []})
        if path == "/Invoice/9002/getCheckAccountTransactionLogs":
            return _FakeResponse(
                {
                    "objects": [
                        {
                            "checkAccountTransaction": {
                                "id": "tx-1",
                                "valueDate": "2026-03-04",
                                "assignedAmountGross": "60.00",
                            }
                        }
                    ]
                }
            )
        if path == "/Invoice/9002/getCheckAccountTransactions":
            return _FakeResponse(
                {
                    "objects": [
                        {
                            "id": "tx-1",
                            "valueDate": "2026-03-04",
                            "assignedAmountGross": "60.00",
                        }
                    ]
                }
            )
        if path == "/InvoicePos":
            return _FakeResponse({"objects": []})
        if path == "/Voucher":
            return _FakeResponse({"objects": []})
        if path == "/CreditNote":
            return _FakeResponse({"objects": []})
        raise AssertionError(f"Unexpected request: {path} {query}")


def test_provider_loads_credit_notes_as_negative_sales() -> None:
    provider = SevdeskUvaPreviewProvider(_CreditNoteConnection())  # type: ignore[arg-type]
    payload_service = UvaPayloadService(UvaPreviewService(provider))

    payload = payload_service.build_payload(2026, 3)

    assert payload.kennzahlen.A029 == "-100.00"


def test_provider_deduplicates_same_transaction_from_two_payment_endpoints() -> None:
    provider = SevdeskUvaPreviewProvider(_PaymentLogDuplicateTxConnection())  # type: ignore[arg-type]
    payload_service = UvaPayloadService(UvaPreviewService(provider))

    payload = payload_service.build_payload(2026, 3)

    assert payload.kennzahlen.A022 == "50.00"


def test_debit_voucher_is_included_as_output_tax(monkeypatch) -> None:
    provider = SevdeskUvaPreviewProvider(_PaymentLogConnection())  # type: ignore[arg-type]
    debit_voucher = {
        "id": "9900",
        "voucherNumber": "ERLOES-13",
        "creditDebit": "D",
        "status": "1000",
        "paidDate": "2026-03-12",
        "voucherDate": "2026-03-01",
        "taxText": "MIT 13% MEHRWERTSTEUER",
        "sumGross": "1130.00",
        "sumNet": "1000.00",
        "sumTax": "130.00",
    }
    monkeypatch.setattr(provider, "_load_resource", lambda *args, **kwargs: [])
    monkeypatch.setattr(provider, "_load_period_overlay", lambda *args, **kwargs: [])
    monkeypatch.setattr(provider, "_load_voucher_candidates", lambda year, month: [debit_voucher])
    monkeypatch.setattr(
        provider, "_enrich_payment_metadata", lambda resource, doc, year, month: dict(doc)
    )
    monkeypatch.setattr(provider, "_prepare_document", lambda resource, doc: dict(doc))

    payload = UvaPayloadService(UvaPreviewService(provider)).build_payload(2026, 3)

    assert payload.kennzahlen.A006 == "1000.00"


def test_june_2026_golden_master_is_reference_data_only() -> None:
    reference_path = Path("config/uva_reference_values.json")
    references = json.loads(reference_path.read_text(encoding="utf-8"))
    reference = references["2026-06"]

    assert sorted(references) == ["2026-04", "2026-05", "2026-06"]
    assert references["2026-04"]["zahlbetrag"] == "267.60"
    assert references["2026-05"]["kennzahlen"]["C065"] == "23.70"
    assert reference["kennzahlen"]["A022"] == "3349.56"
    assert reference["kennzahlen"]["A000"] == "21061.38"
    assert reference["kennzahlen"]["A006"] == "9216.97"
    assert reference["kennzahlen"]["C060"] == "416.46"
    assert reference["zahlbetrag"] == "1910.22"
    assert all(item["immutable_reference"] is True for item in references.values())


def test_uva_references_are_loaded_as_immutable_mapping() -> None:
    references = load_uva_references()

    assert references["2026-04"]["zahlbetrag"] == "267.60"
    try:
        references["2026-04"] = {}  # type: ignore[index]
    except TypeError:
        pass
    else:  # pragma: no cover - defensive assertion.
        raise AssertionError("Reference mapping must be immutable")


def test_uva_reference_comparison_reports_deltas_without_overriding() -> None:
    comparison = compare_uva_reference(
        year=2026,
        month=6,
        kennzahlen={"A000": "21195.54", "A017": "3668.46", "A022": "3349.56"},
        zahlbetrag="1910.30",
    )

    assert comparison["available"] is True
    assert comparison["zahlbetrag"]["delta"] == "0.08"
    assert comparison["zahlbetrag"]["within_tolerance"] is True
    deltas = {item["field"]: item for item in comparison["deltas"]}
    assert deltas["A000"]["delta"] == "134.16"
    assert deltas["A017"]["delta"] == "134.16"


def _semantic_preview_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and line.strip() != "------------"
    ]
