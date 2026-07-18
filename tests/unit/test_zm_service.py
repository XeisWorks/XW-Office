from __future__ import annotations

from xw_studio.services.finanzonline.zm_service import ZmService


class _Provider:
    def load_invoices(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 5)
        return [
            {
                "id": "1",
                "invoiceNumber": "RE-1",
                "invoiceDate": "2026-05-02",
                "status": "100",
                "taxType": "eu",
                "taxRule": {"id": "3"},
                "sumNet": "100.40",
                "contact": {"name": "EU Kunde", "vatNumber": " DE 136695976 "},
            },
            {
                "id": "2",
                "invoiceNumber": "RE-2",
                "invoiceDate": "2026-05-04",
                "status": "1000",
                "taxRule": {"id": "5"},
                "taxText": "Reverse Charge sonstige Leistung",
                "sumNet": "200.50",
                "contact": {"name": "Service Kunde", "vatNumber": "IT00743110157"},
            },
            {
                "id": "3",
                "invoiceNumber": "RE-3",
                "invoiceDate": "2026-05-05",
                "status": "100",
                "taxType": "eu",
                "taxRule": {"id": "3"},
                "sumNetAccounting": "50.00",
                "contact": {"name": "Ohne UID", "vatNumber": ""},
            },
            {
                "id": "4",
                "invoiceNumber": "RE-4",
                "invoiceDate": "2026-06-01",
                "status": "100",
                "taxType": "eu",
                "sumNet": "999.00",
                "contact": {"name": "Falscher Monat", "vatNumber": "DE136695976"},
            },
            {
                "id": "5",
                "invoiceNumber": "RE-5",
                "invoiceDate": "2026-05-06",
                "status": "100",
                "taxType": "eu",
                "taxRule": {"id": "3"},
                "sumNet": "10.00",
                "contact": {"name": "AT falsch klassifiziert", "vatNumber": "ATU12345678"},
            },
        ]


class _ProviderWithCreditNote:
    def load_invoices(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 5)
        return [
            {
                "id": "10",
                "invoiceNumber": "RE-10",
                "invoiceDate": "2026-05-02",
                "status": "1000",
                "taxType": "eu",
                "taxRule": {"id": "3"},
                "sumNet": "500.00",
                "contact": {"name": "EU Kunde", "vatNumber": "DE136695976"},
            }
        ]

    def load_credit_notes(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 5)
        return [
            {
                "id": "11",
                "creditNoteNumber": "GU-11",
                "creditNoteDate": "2026-05-20",
                "status": "1000",
                "taxType": "eu",
                "taxRule": {"id": "3"},
                "sumNet": "125.40",
                "contact": {"name": "EU Kunde", "vatNumber": "DE136695976"},
            }
        ]


def test_zm_service_uses_invoice_date_and_groups_by_uid_and_kind() -> None:
    result = ZmService(_Provider()).calculate_month(2026, 5)  # type: ignore[arg-type]

    assert result.considered == 5
    assert result.selected == 4
    assert len(result.rows) == 2
    assert result.total_eur_int == 301
    assert [(row.uid, row.kind, row.amount_eur_int) for row in result.rows] == [
        ("DE136695976", "delivery", 100),
        ("IT00743110157", "service", 201),
    ]
    assert result.invalid == [
        "ungueltige/fehlende UID: Ohne UID (RE-3) -> leer",
        "ungueltige/fehlende UID: AT falsch klassifiziert (RE-5) -> ATU12345678",
    ]


def test_zm_service_subtracts_credit_notes_by_credit_note_date() -> None:
    result = ZmService(_ProviderWithCreditNote()).calculate_month(2026, 5)  # type: ignore[arg-type]

    assert result.considered == 2
    assert result.selected == 2
    assert len(result.rows) == 1
    assert result.rows[0].uid == "DE136695976"
    assert result.rows[0].amount_eur_int == 375
    assert result.rows[0].invoice_numbers == ["RE-10", "GU-11"]


class _ProviderWithMixedPositions:
    def __init__(self) -> None:
        self.position_calls: list[tuple[str, str]] = []

    def load_invoices(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 5)
        return [
            {
                "id": "20",
                "invoiceNumber": "RE-20",
                "invoiceDate": "2026-05-08",
                "status": "100",
                "taxType": "eu",
                "taxRule": {"id": "3"},
                "sumNet": "999.00",
                "contact": {"name": "EU Kunde", "vatNumber": "DE136695976"},
            }
        ]

    def load_positions(self, resource: str, document_id: str) -> list[dict[str, object]]:
        self.position_calls.append((resource, document_id))
        return [
            {"sumNet": "100.40", "taxType": "eu", "taxRule": {"id": "3"}},
            {"sumNet": "200.50", "taxText": "Reverse Charge sonstige Leistung"},
            {"sumNet": "698.10", "taxText": "MIT 20% MEHRWERTSTEUER"},
        ]


def test_zm_service_uses_relevant_positions_when_available() -> None:
    provider = _ProviderWithMixedPositions()
    result = ZmService(provider).calculate_month(2026, 5)  # type: ignore[arg-type]

    assert result.considered == 1
    assert result.selected == 1
    assert provider.position_calls == [("Invoice", "20")]
    assert [(row.uid, row.kind, row.amount_eur_int, row.invoice_numbers) for row in result.rows] == [
        ("DE136695976", "delivery", 100, ["RE-20"]),
        ("DE136695976", "service", 201, ["RE-20"]),
    ]


class _ProviderWithMismatchingPositions(_ProviderWithMixedPositions):
    def load_invoices(self, year: int, month: int) -> list[dict[str, object]]:
        rows = super().load_invoices(year, month)
        rows[0]["sumNet"] = "285.26"
        return rows


def test_zm_service_falls_back_to_document_net_when_positions_do_not_match() -> None:
    result = ZmService(_ProviderWithMismatchingPositions()).calculate_month(2026, 5)  # type: ignore[arg-type]

    assert [(row.uid, row.kind, row.amount_eur_int) for row in result.rows] == [
        ("DE136695976", "delivery", 285),
    ]
    assert any("Positionssumme" in warning for warning in result.warnings)
