"""Unit tests for MusikHeroes commission calculation service."""
from __future__ import annotations

from datetime import date

from xw_studio.services.commission.service import CommissionService


class _ProviderStub:
    def __init__(self) -> None:
        self.cache_cleared = 0
        self._categories = [{"id": "cat_mh", "name": "MusikHeroes"}]
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

    def list_credit_notes_for_year(self, year: int) -> list[dict[str, object]]:
        if year != 2026:
            return []
        return [dict(item) for item in self._credit_notes]

    def list_credit_note_positions(self, credit_note_id: str) -> list[dict[str, object]]:
        return [dict(item) for item in self._credit_positions.get(credit_note_id, [])]


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
