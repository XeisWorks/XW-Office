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
