"""Complete, reconciled sevDesk payment evidence for cash-basis tax selection."""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from xw_office.core.exceptions import SevdeskApiError
from xw_office.services.finanzonline.amounts import tax_amount
from xw_office.services.finanzonline.source_reads import TaxPageLimitError, load_tax_resource
from xw_office.services.http_client import SevdeskConnection

logger = logging.getLogger(__name__)
_DATE_KEYS = ("bookingDate", "valueDate", "entryDate", "date", "created", "create")
_AMOUNT_KEYS = ("amountPaid", "assignedAmount", "assignedAmountGross", "paymentAmount", "amount", "value", "sum")


class SevdeskPaymentEvidence:
    def __init__(self, connection: SevdeskConnection) -> None:
        self._connection = connection
        self.logs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.complete = False
        self.warnings: list[str] = []

    def clear(self) -> None:
        self.logs.clear()
        self.complete = False
        self.warnings.clear()

    def prepare(self) -> None:
        self.logs.clear()
        self.complete = False
        try:
            rows = load_tax_resource(self._connection, "/CheckAccountTransactionLog")
            grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for row in rows:
                reference = row.get("object")
                if not isinstance(reference, dict) or not reference.get("id") or not reference.get("objectName"):
                    raise ValueError("Zahlungszuordnung ohne Belegreferenz")
                key = (str(reference["objectName"]), str(reference["id"]))
                grouped.setdefault(key, []).append(row)
        except SevdeskApiError as exc:
            if exc.status_code not in {404, 405}:
                raise
            logger.warning("Bulk payment endpoint unavailable; verifying individual documents: %s", exc)
            return
        except (TaxPageLimitError, ValueError) as exc:
            logger.warning("Bulk payment evidence incomplete; verifying individual documents: %s", exc)
            return
        self.logs = grouped
        self.complete = True

    def load(
        self, resource: str, doc_id: str, year: int, month: int,
        *, expected_paid_amount: Decimal | None = None,
        gross_amount: Decimal | None = None,
        evidence_date: datetime | None = None,
    ) -> tuple[str | None, str | None]:
        events: list[dict[str, Any]] = []
        logged_transaction_ids: set[str] = set()
        seen_transactions: set[str] = set()
        failures: list[httpx.HTTPError] = []
        for suffix in ("getCheckAccountTransactionLogs", "getCheckAccountTransactions"):
            try:
                bulk = self.logs.get((resource, doc_id), []) if self.complete else None
                if suffix == "getCheckAccountTransactionLogs" and bulk is not None:
                    payload = {"objects": bulk}
                else:
                    payload = self._connection.get(f"/{resource}/{doc_id}/{suffix}").json()
            except httpx.HTTPError as exc:
                logger.warning("Payment metadata lookup failed for %s/%s via %s: %s", resource, doc_id, suffix, exc)
                failures.append(exc)
                continue
            objects = payload.get("objects") if isinstance(payload, dict) else None
            if not isinstance(objects, list):
                raise ValueError(f"UVA: Ungueltige Zahlungsnachweise fuer {resource}/{doc_id}.")
            seen_log_rows: set[str] = set()
            for item in objects:
                if not isinstance(item, dict):
                    raise ValueError(f"UVA: Ungueltiger Zahlungsnachweis fuer {resource}/{doc_id}.")
                tx_id = _transaction_id(item)
                if suffix == "getCheckAccountTransactionLogs":
                    row_id = str(item.get("id") or "").strip()
                    if row_id and row_id in seen_log_rows:
                        continue
                    if row_id:
                        seen_log_rows.add(row_id)
                    if tx_id is not None:
                        logged_transaction_ids.add(tx_id)
                elif tx_id is not None and tx_id in logged_transaction_ids:
                    event_date = _event_date(item)
                    if event_date is not None:
                        for event in events:
                            if _transaction_id(event) == tx_id and _event_date(event) is None:
                                event["bookingDate"] = event_date.isoformat()
                    continue
                elif tx_id is not None and tx_id in seen_transactions:
                    continue
                if suffix == "getCheckAccountTransactions" and tx_id is not None:
                    seen_transactions.add(tx_id)
                events.append(item)
            # Complete assignment evidence avoids a redundant bank-transaction read.
            if (
                suffix == "getCheckAccountTransactionLogs"
                and events and expected_paid_amount is not None
                and expected_paid_amount > Decimal("0.00")
                and all(_event_date(item) is not None and _event_amount(item) > Decimal("0.00") for item in events)
                and abs(sum((_event_amount(item) for item in events), Decimal(0)) - expected_paid_amount)
                <= Decimal("0.005")
            ):
                break
        if not events and failures:
            raise RuntimeError(
                f"UVA: Zahlungsnachweise fuer {resource}/{doc_id} konnten nicht geladen werden."
            ) from failures[-1]
        if not events:
            return None, None
        if any(_event_date(event) is None or _event_amount(event) <= Decimal("0.00") for event in events):
            raise ValueError(f"UVA: Unvollstaendiger Zahlungsnachweis fuer {resource}/{doc_id}.")
        total_paid = sum((_event_amount(event) for event in events), Decimal(0))
        payment_cap: Decimal | None = None
        if (
            expected_paid_amount is not None and gross_amount is not None
            and gross_amount > Decimal(0)
            and abs(expected_paid_amount - gross_amount) <= Decimal("0.005")
            and total_paid > gross_amount
        ):
            payment_cap = gross_amount
            self.warnings.append(
                f"Zahlungsueberschuss nicht nochmals als Belegumsatz erfasst: "
                f"{resource}/{doc_id}, {tax_amount(total_paid - gross_amount):.2f} EUR. "
                "Verrechnung des Ueberschusses pruefen."
            )
        if (
            expected_paid_amount is not None and payment_cap is None
            and abs(total_paid - expected_paid_amount) > Decimal("0.005")
        ):
            raise ValueError(
                f"UVA: Zahlungsnachweise und bezahlter Belegbetrag widersprechen sich fuer {resource}/{doc_id}."
            )
        any_payment_date: datetime | None = None
        period_payment_date: datetime | None = None
        period_paid_amount = Decimal("0.00")
        events.sort(key=_event_sort_key)
        remaining = payment_cap
        for event in events:
            event_date = _event_date(event)
            if evidence_date is not None and event_date is not None and evidence_date.date() > event_date.date():
                event_date = evidence_date
            amount = _event_amount(event)
            if remaining is not None:
                amount = min(amount, remaining)
                remaining -= amount
            if event_date is not None and (any_payment_date is None or event_date.date() > any_payment_date.date()):
                any_payment_date = event_date
            if event_date is None or event_date.year != year or event_date.month != month:
                continue
            if period_payment_date is None or event_date.date() > period_payment_date.date():
                period_payment_date = event_date
            if amount > Decimal("0.00"):
                period_paid_amount += amount
        payment_date = period_payment_date or any_payment_date
        return (
            payment_date.isoformat() if payment_date is not None else None,
            f"{tax_amount(period_paid_amount):.2f}",
        )


def parse_source_date(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _event_nodes(event: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [event]
    nested = event.get("checkAccountTransaction")
    if isinstance(nested, dict):
        nodes.append(nested)
    return nodes


def _event_date(event: dict[str, Any]) -> datetime | None:
    for node in _event_nodes(event):
        for key in _DATE_KEYS:
            result = parse_source_date(node.get(key))
            if result is not None:
                return result
    return None


def _event_sort_key(event: dict[str, Any]) -> float:
    event_date = _event_date(event)
    if event_date is None:
        raise ValueError("UVA: Zahlungsdatum fehlt.")
    return event_date.timestamp()


def _event_amount(event: dict[str, Any]) -> Decimal:
    for node in _event_nodes(event):
        for key in _AMOUNT_KEYS:
            if key in node:
                amount = abs(tax_amount(node.get(key)))
                if amount > Decimal("0.00"):
                    return amount
    return Decimal("0.00")


def _transaction_id(event: dict[str, Any]) -> str | None:
    nested = event.get("checkAccountTransaction")
    if isinstance(nested, dict) and nested.get("id") not in (None, ""):
        return str(nested["id"]).strip()
    for key in ("checkAccountTransactionId", "transactionId"):
        if event.get(key) not in (None, ""):
            return str(event[key]).strip()
    for node in _event_nodes(event):
        for key in ("checkAccountTransactionId", "transactionId", "id"):
            value = node.get(key)
            if value not in (None, ""):
                text = str(value).strip()
                if text:
                    return text
    return None
