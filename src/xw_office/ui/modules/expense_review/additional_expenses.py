"""Read-only presentation of manual expenses and XeisWorks-funded WM bank expenses."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from xw_office.services.commission.service import format_euro_amount
from xw_office.services.expenses.service import BankExpenseRow, ExpensePositionView
from xw_office.services.expenses.xw_flow_expense_client import FlowExpense


ADDITIONAL_EXPENSE_HEADERS = [
    "Datum", "Empfänger", "Zweck", "Betrag", "USt.", "Zahlungsart",
    "Kategorie", "Beleg", "Prüfung", "Rückzahlung", "Herkunft",
]


def manual_expense_rows(
    expenses: list[FlowExpense], positions: list[ExpensePositionView], *, tenant_key: str
) -> list[dict[str, Any]]:
    position_data = [position.__dict__ for position in positions] if tenant_key == "xw" else []
    return [
        {
            "Datum": item.expense_date or "offen",
            "Empfänger": item.recipient,
            "Zweck": item.purpose,
            "Betrag": format_euro_amount(item.gross_amount or Decimal("0")),
            "USt.": f"{item.tax_rate_bps / 100:g} %" if item.tax_rate_bps is not None else "unbekannt",
            "Zahlungsart": item.payment_source,
            "Kategorie": "",
            "Beleg": "      " if item.attachment_ids else "fehlt",
            "Prüfung": item.accounting_status,
            "Rückzahlung": item.reimbursement_status,
            "Herkunft": "XeisWorks · manuell" if item.tenant_key == "xw" else "WüdaraMusi · manuell",
            "__transaction_id": f"manual:{item.id}",
            "__manual_id": item.id,
            "__manual_version": item.version,
            "__manual_attachment_ids": list(item.attachment_ids),
            "__source_tenant": item.tenant_key,
            "__positions": position_data,
            "__position_key": item.category_key,
            "__align__Betrag": "right",
            "__align__Kategorie": "center",
            "__fg__Betrag": "#ff9c9c",
            "__tooltip__Beleg": "Beleg öffnen" if item.attachment_ids else "Kein Beleg angehängt",
        }
        for item in expenses
        if item.tenant_key == tenant_key
        or (tenant_key == "wuedara" and item.tenant_key == "xw" and item.category_key == "wm")
    ]


def shared_bank_expense_rows(expenses: list[BankExpenseRow]) -> list[dict[str, Any]]:
    return [
        {
            "Datum": row.value_date.isoformat(),
            "Empfänger": row.payee,
            "Zweck": row.purpose,
            "Betrag": format_euro_amount(-row.amount),
            "USt.": "unbekannt",
            "Zahlungsart": "XeisWorks-Konto",
            "Kategorie": "",
            "Beleg": "     " * (len(row.documents) + 1),
            "Prüfung": "Belegscan unvollständig" if not row.document_link_scan_complete else "",
            "Rückzahlung": "",
            "Herkunft": "XeisWorks · Konto",
            "__transaction_id": f"xw-bank:{row.transaction_id}",
            "__source_transaction_id": row.transaction_id,
            "__source_tenant": "xw",
            "__documents": [document.__dict__ for document in row.documents],
            "__supplier_url": row.supplier_url,
            "__read_only": True,
            "__align__Betrag": "right",
            "__fg__Betrag": "#ff9c9c",
            "__tooltip__Beleg": "\n".join(
                [f"sevDesk XeisWorks: {doc.document_number}" for doc in row.documents]
                + (["Lieferantenportal öffnen"] if row.supplier_url else [])
            ),
            "__tooltip__Herkunft": "WM-Zuordnung im Bereich XeisWorks bearbeiten",
        }
        for row in expenses
    ]
