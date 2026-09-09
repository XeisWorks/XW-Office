"""Unit tests for MusikHeroes commission calculation service."""

from __future__ import annotations

from datetime import date

from xw_office.services.commission.service import (
    CommissionPeriod,
    CommissionProfile,
    CommissionRunResult,
    CommissionService,
    CommissionSummary,
    ProductBreakdownRow,
    SevdeskCommissionProvider,
    format_commission_summary,
)


class _ProviderStub:
    def __init__(self) -> None:
        self.cache_cleared = 0
        self._categories = [
            {"id": "cat_mh", "name": "MusikHeroes"},
            {"id": "cat_mh_notes", "name": "MusikHeroes_Noten digital"},
            {"id": "cat_mh_playalongs", "name": "MusikHeroes_Playalongs digital"},
            {"id": "cat_mh_print", "name": "MusikHeroes_Print@Home"},
        ]
        self._parts = [
            {
                "id": "part_1",
                "sku": "XW-511.09",
                "name": "MusikHeroes Heft",
                "category_id": "cat_mh",
                "category_name": "MusikHeroes",
            }
        ]
        self._invoices = [
            {
                "id": "inv_re_1",
                "invoiceNumber": "RE-261880",
                "invoiceDate": "2026-06-08",
                "invoiceType": "RE",
            },
            {
                "id": "inv_re_2",
                "invoiceNumber": "RE-261929",
                "invoiceDate": "2026-06-17",
                "invoiceType": "RE",
            },
            {
                "id": "inv_sr_1",
                "invoiceNumber": "RE-261922",
                "invoiceDate": "2026-06-18",
                "invoiceType": "SR",
            },
        ]
        self._invoice_positions = {
            "inv_re_1": [
                {
                    "part": {"id": "part_1", "partNumber": "XW-511.09", "name": "MusikHeroes Heft"},
                    "quantity": 1,
                    "sumNet": 22.64,
                    "sumGross": 24.90,
                }
            ],
            "inv_re_2": [
                {
                    "part": {"id": "part_1", "partNumber": "XW-511.09", "name": "MusikHeroes Heft"},
                    "quantity": 1,
                    "sumNet": 22.64,
                    "sumGross": 24.90,
                }
            ],
            "inv_sr_1": [
                {
                    "part": {"id": "part_1", "partNumber": "XW-511.09", "name": "MusikHeroes Heft"},
                    "quantity": 7,
                    "sumNet": -116.18,
                    "sumGross": -127.80,
                }
            ],
        }
        self._credit_notes = [
            {
                "id": "cr_1",
                "creditNoteNumber": "GS-1",
                "creditNoteDate": "2026-07-02",
            }
        ]
        self._credit_positions = {
            "cr_1": [
                {
                    "part": {"id": "part_1", "partNumber": "XW-511.09", "name": "MusikHeroes Heft"},
                    "quantity": 1,
                    "sumNet": -22.64,
                    "sumGross": -24.90,
                }
            ]
        }

    def clear_cache(self) -> None:
        self.cache_cleared += 1

    def list_part_categories(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._categories]

    def list_parts(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._parts]

    def list_invoices_for_year(self, year: int) -> list[dict[str, object]]:
        if year != 2026:
            return []
        return [dict(item) for item in self._invoices]

    def list_invoice_positions(self, invoice_id: str) -> list[dict[str, object]]:
        return [dict(item) for item in self._invoice_positions.get(invoice_id, [])]

    def list_invoice_positions_bulk(self, invoice_ids: list[str]) -> list[dict[str, object]]:
        return [
            {**dict(item), "invoice": {"id": invoice_id}}
            for invoice_id in invoice_ids
            for item in self._invoice_positions.get(invoice_id, [])
        ]

    def list_credit_notes_for_year(self, year: int) -> list[dict[str, object]]:
        if year != 2026:
            return []
        return [dict(item) for item in self._credit_notes]

    def list_credit_note_positions(self, credit_note_id: str) -> list[dict[str, object]]:
        return [dict(item) for item in self._credit_positions.get(credit_note_id, [])]

    def list_credit_note_positions_bulk(
        self, credit_note_ids: list[str]
    ) -> list[dict[str, object]]:
        return [
            {**dict(item), "creditNote": {"id": credit_note_id}}
            for credit_note_id in credit_note_ids
            for item in self._credit_positions.get(credit_note_id, [])
        ]


def test_musikheroes_sr_keeps_negative_net_and_quantity() -> None:
    provider = _ProviderStub()
    service = CommissionService(provider)
    period = service.resolve_period(
        "custom",
        reference_date=date(2026, 7, 8),
        custom_start=date(2026, 6, 1),
        custom_end=date(2026, 6, 30),
    )

    result = service.run_profile("musikheroes", period)

    assert result.summary.total_net_quantity == -5.0
    assert round(result.summary.total_net_amount, 2) == -70.90
    assert result.summary.anomaly_count == 0
    row = result.product_rows[0]
    assert row.sold_quantity == 2.0
    assert row.canceled_quantity == 7.0
    assert row.net_quantity == -5.0
    assert round(row.net_amount, 2) == -70.90


def test_credit_note_uses_credit_note_date_not_origin_invoice_date() -> None:
    provider = _ProviderStub()
    service = CommissionService(provider)
    june_period = service.resolve_period(
        "custom",
        reference_date=date(2026, 7, 8),
        custom_start=date(2026, 6, 1),
        custom_end=date(2026, 6, 30),
    )

    june_result = service.run_profile("musikheroes", june_period)
    july_period = service.resolve_period(
        "custom",
        reference_date=date(2026, 7, 8),
        custom_start=date(2026, 7, 1),
        custom_end=date(2026, 7, 31),
    )
    july_result = service.run_profile("musikheroes", july_period)

    assert june_result.summary.document_count == 3
    assert july_result.summary.document_count == 1
    assert round(july_result.summary.total_net_amount, 2) == -22.64


def test_refresh_data_clears_provider_cache() -> None:
    provider = _ProviderStub()
    service = CommissionService(provider)
    period = service.resolve_period(
        "custom",
        reference_date=date(2026, 7, 8),
        custom_start=date(2026, 6, 1),
        custom_end=date(2026, 6, 30),
    )

    service.run_profile("musikheroes", period, refresh_data=True)

    assert provider.cache_cleared == 1


def test_category_profile_excludes_free_text_and_other_category_products() -> None:
    provider = _ProviderStub()
    provider._parts.append(
        {
            "id": "part_vam",
            "sku": "XW-6612",
            "name": "Mnoschil",
            "category_id": "cat_vam",
            "category_name": "Vienna Arts Management",
        }
    )
    provider._invoice_positions["inv_re_1"].extend(
        [
            {
                "part": {"id": "part_vam", "partNumber": "XW-6612", "name": "Mnoschil"},
                "quantity": 19,
                "sumNet": 811.25,
                "sumGross": 892.38,
            },
            {
                "name": "Mnoschil",
                "category": {"id": "cat_mh", "name": "MusikHeroes"},
                "quantity": 19,
                "sumNet": 811.25,
                "sumGross": 892.38,
            },
        ]
    )
    service = CommissionService(provider)
    period = service.resolve_period(
        "custom",
        reference_date=date(2026, 7, 8),
        custom_start=date(2026, 6, 1),
        custom_end=date(2026, 6, 30),
    )

    result = service.run_profile("musikheroes", period)

    assert round(result.summary.total_net_amount, 2) == -70.90
    assert all(row.name != "Mnoschil" for row in result.product_rows)
    assert result.source_stats["positions_skipped_no_profile_match"] == 2


def test_missing_configured_category_fails_closed() -> None:
    provider = _ProviderStub()
    provider._categories = []
    service = CommissionService(provider)
    period = service.resolve_period(
        "custom",
        reference_date=date(2026, 7, 8),
        custom_start=date(2026, 6, 1),
        custom_end=date(2026, 6, 30),
    )

    try:
        service.run_profile("musikheroes", period)
    except RuntimeError as exc:
        assert "Kategorie nicht gefunden" in str(exc)
    else:
        raise AssertionError("missing category must not produce an unfiltered result")


def test_last_half_year_is_previous_completed_calendar_half_year() -> None:
    service = CommissionService(_ProviderStub())

    first_half = service.resolve_period("last_half_year", reference_date=date(2026, 9, 9))
    second_half = service.resolve_period("last_half_year", reference_date=date(2026, 3, 1))

    assert (first_half.start, first_half.end) == (date(2026, 1, 1), date(2026, 6, 30))
    assert (second_half.start, second_half.end) == (date(2025, 7, 1), date(2025, 12, 31))


def test_mnozil_profile_resolves_the_sevdesk_category() -> None:
    service = CommissionService(_ProviderStub())

    profile = service.get_profile("mnozil")
    assert profile.label == "Mnozil Brass"
    assert profile.category_names == ("Mnozil",)
    assert profile.commission_rate_percent == 25.0


def test_clipboard_summary_matches_legacy_layout_with_german_numbers() -> None:
    result = CommissionRunResult(
        profile=CommissionProfile(
            key="mnozil",
            label="Mnozil Brass",
            category_names=("Mnozil",),
            commission_rate_percent=25.0,
        ),
        period=CommissionPeriod(
            start=date(2026, 1, 1),
            end=date(2026, 6, 30),
            basis="invoice_date",
            reference_date=date(2026, 9, 9),
        ),
        summary=CommissionSummary(total_net_quantity=154, total_net_amount=2683.04),
        product_rows=[
            ProductBreakdownRow(
                sku="XW-4516",
                name="Mnoschil",
                net_quantity=45,
                net_amount=625.70,
            ),
            ProductBreakdownRow(
                sku="XW-4556",
                name="Florentiner Marsch",
                net_quantity=9,
                net_amount=202.45,
            ),
        ],
        category_rows=[],
        document_rows=[],
        anomalies=[],
        source_stats={},
    )

    assert format_commission_summary(result) == (
        "Kategorie: Mnozil Brass\n"
        "Zeitraum: 01.01.2026 - 30.06.2026\n"
        "Basisdatum: Rechnungsdatum\n"
        "SKU-Filter: Filter: sevDesk-Kategorie Mnozil\n"
        "Gesamtmenge: 154\n"
        "Netto gesamt: 2.683,04 EUR\n"
        "\n"
        "Produkte:\n"
        "SKU\tName\tMenge\tNetto\n"
        "\n"
        "XW-4516\tMnoschil\t45 Stk.\t625,70 EUR netto\n"
        "XW-4556\tFlorentiner Marsch\t9 Stk.\t202,45 EUR netto\n"
        "\n"
        "Rechnungsbetrag (25%): € 670,76"
    )


def test_provider_bulk_positions_loads_one_snapshot_and_filters_locally() -> None:
    class _Response:
        def json(self) -> dict[str, object]:
            return {
                "objects": [
                    {"id": "p1", "invoice": {"id": "a"}},
                    {"id": "p2", "invoice": {"id": "b"}},
                    {"id": "p3", "invoice": {"id": "c"}},
                ]
            }

    class _Connection:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, path: str, **kwargs: object) -> _Response:
            assert path == "/InvoicePos"
            assert kwargs["params"] == {"limit": 5_000, "offset": 0, "embed": "part"}
            self.calls += 1
            return _Response()

    connection = _Connection()
    provider = SevdeskCommissionProvider(connection, object())  # type: ignore[arg-type]

    first = provider.list_invoice_positions_bulk(["a", "c"])
    second = provider.list_invoice_positions_bulk(["b"])

    assert [row["id"] for row in first] == ["p1", "p3"]
    assert [row["id"] for row in second] == ["p2"]
    assert connection.calls == 1
