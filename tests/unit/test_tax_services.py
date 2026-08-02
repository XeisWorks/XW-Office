"""Tests for clearing and expense services."""
from __future__ import annotations

import json

from xw_office.services.clearing.service import PaymentClearingService
from xw_office.services.expenses.service import ExpenseAuditService


class _RepoStub:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get_value_json(self, key: str) -> str | None:
        return self._values.get(key)


def test_clearing_load_filter_export() -> None:
    repo = _RepoStub(
        {
            "daily_business.queue.mollie": json.dumps(
                [
                    {
                        "ref": "MOL-1",
                        "customer": "Anna",
                        "amount": "19.90",
                        "status": "offen",
                        "note": "warte auf match",
                    },
                    {
                        "ref": "MOL-2",
                        "customer": "Bert",
                        "amount": "29.90",
                        "status": "done",
                        "note": "ok",
                    },
                ]
            )
        }
    )
    svc = PaymentClearingService(repo)  # type: ignore[arg-type]

    rows = svc.list_pending()
    assert len(rows) == 2

    filtered = svc.filter_rows(rows, needle="anna", status="offen")
    assert len(filtered) == 1
    assert filtered[0].ref == "MOL-1"

    csv_payload = svc.export_csv(filtered)
    assert "Ref;Kunde;Betrag;Status;Hinweis" in csv_payload
    assert "MOL-1;Anna;19.90;offen;warte auf match" in csv_payload


def test_expenses_load_filter_export() -> None:
    repo = _RepoStub(
        {
            "expenses.open_items": json.dumps(
                [
                    {
                        "ref": "EXP-1",
                        "supplier": "Papier AG",
                        "gross_amount": "49.00",
                        "category": "Material",
                        "status": "offen",
                        "note": "Beleg fehlt",
                    },
                    {
                        "ref": "EXP-2",
                        "supplier": "Druck GmbH",
                        "gross_amount": "120.00",
                        "category": "Druck",
                        "status": "done",
                        "note": "gebucht",
                    },
                ]
            )
        }
    )
    svc = ExpenseAuditService(repo)  # type: ignore[arg-type]

    rows = svc.list_open()
    assert len(rows) == 2

    filtered = svc.filter_rows(rows, needle="papier", status="offen")
    assert len(filtered) == 1
    assert filtered[0].ref == "EXP-1"

    csv_payload = svc.export_csv(filtered)
    assert "Ref;Lieferant;Brutto;Kategorie;Status;Hinweis" in csv_payload
    assert "EXP-1;Papier AG;49.00;Material;offen;Beleg fehlt" in csv_payload
