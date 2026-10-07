"""Read-only sevDesk bank provider used by Ausgabenprüfung."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from xw_office.core.text_normalize import normalize_german_text
from xw_office.services.http_client import SevdeskConnection

VIENNA = ZoneInfo("Europe/Vienna")


@dataclass(frozen=True)
class SevdeskBankAccount:
    id: str
    name: str
    last_sync_at: datetime | None


@dataclass(frozen=True)
class BankDocumentLink:
    transaction_external_id: str
    resource_type: str
    external_id: str
    document_number: str


@dataclass(frozen=True)
class BankExpense:
    external_id: str
    account_id: str
    value_date: date
    entry_date: date | None
    amount: Decimal
    currency: str
    direction: str
    payee_name: str
    payee_normalized: str
    counterparty_iban: str
    payment_reference: str
    purpose: str
    sevdesk_status: str

    @property
    def display_reference(self) -> str:
        return self.payment_reference or self.purpose


def _objects(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("objects", payload.get("data", []))
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        raw = int(value)
        if raw >= 10**12:
            raw //= 1000
        result = datetime.fromtimestamp(raw, tz=UTC)
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(VIENNA)


def _parse_date(value: object) -> date | None:
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed.date()
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "."))
    except Exception:  # noqa: BLE001
        return Decimal(0)


class SevdeskExpenseProvider:
    """Fetch one named CheckAccount and its outgoing transactions."""

    def __init__(
        self,
        connection: SevdeskConnection,
        *,
        account_name: str = "XeisWorks",
        base_url: str = "https://my.sevdesk.de/api/v1",
    ) -> None:
        self._connection = connection
        self._account_name = account_name.strip()
        self.base_url = base_url.strip()

    def find_account(self) -> SevdeskBankAccount:
        for raw in self._list("/CheckAccount"):
            if str(raw.get("name") or "").strip().casefold() != self._account_name.casefold():
                continue
            account_id = str(raw.get("id") or "").strip()
            if not account_id:
                continue
            last_sync = _parse_datetime(raw.get("lastSync") or raw.get("lastSyncDate"))
            return SevdeskBankAccount(account_id, self._account_name, last_sync)
        raise RuntimeError(f"sevDesk-Konto '{self._account_name}' wurde nicht gefunden.")

    def fetch(self, start: date, end: date, *, outgoing_only: bool = True) -> tuple[SevdeskBankAccount, list[BankExpense]]:
        account = self.find_account()
        rows: list[BankExpense] = []
        for raw in self._list(
            "/CheckAccountTransaction",
            params={
                "checkAccount[id]": account.id,
                "checkAccount[objectName]": "CheckAccount",
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
            },
        ):
            value_date = _parse_date(raw.get("valueDate") or raw.get("date"))
            if value_date is None or value_date < start or value_date > end:
                continue
            amount = _decimal(raw.get("amount"))
            if outgoing_only and amount >= 0:
                continue
            direction = "outgoing" if amount < 0 else "incoming"
            payee = str(raw.get("payeePayerName") or "").strip()
            payment_reference = str(raw.get("paymentReference") or raw.get("reference") or "").strip()
            purpose = str(raw.get("paymtPurpose") or "").strip()
            rows.append(
                BankExpense(
                    external_id=str(raw.get("id") or "").strip(),
                    account_id=account.id,
                    value_date=value_date,
                    entry_date=_parse_date(raw.get("entryDate")),
                    amount=amount,
                    currency=str(raw.get("currency") or "EUR").strip().upper(),
                    direction=direction,
                    payee_name=payee,
                    payee_normalized=normalize_german_text(payee),
                    counterparty_iban=str(
                        raw.get("payeePayerAcctNo") or raw.get("payeePayerIban") or ""
                    ).strip().replace(" ", "").upper(),
                    payment_reference=payment_reference,
                    purpose=purpose,
                    sevdesk_status=str(raw.get("status") or "").strip(),
                )
            )
        rows.sort(key=lambda row: (row.value_date, row.external_id))
        return account, rows

    def resolve_document_links(
        self, start: date, end: date, *, account_id: str | None = None
    ) -> list[BankDocumentLink]:
        """Resolve concrete sevDesk documents to bank transactions in one scan."""
        links: list[BankDocumentLink] = []
        for resource_type, number_key, date_key in (
            ("Invoice", "invoiceNumber", "invoiceDate"),
            ("Voucher", "voucherNumber", "voucherDate"),
            ("CreditNote", "creditNoteNumber", "creditNoteDate"),
        ):
            documents = self._list(
                f"/{resource_type}",
                params={
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "showAll": "true",
                },
            )
            for document in documents:
                document_id = str(document.get("id") or "").strip()
                document_date = _parse_date(document.get(date_key) or document.get("date"))
                if not document_id or document_date is None or not start <= document_date <= end:
                    continue
                response = self._connection.get(
                    f"/Resource/{document_id}/getCheckAccountTransactions"
                )
                for transaction in _objects(response.json()):
                    transaction_id = str(transaction.get("id") or "").strip()
                    transaction_account = transaction.get("checkAccount")
                    linked_account_id = (
                        str(transaction_account.get("id") or "").strip()
                        if isinstance(transaction_account, dict)
                        else ""
                    )
                    if account_id and linked_account_id and linked_account_id != account_id:
                        continue
                    if transaction_id:
                        links.append(
                            BankDocumentLink(
                                transaction_external_id=transaction_id,
                                resource_type=resource_type,
                                external_id=document_id,
                                document_number=str(
                                    document.get(number_key) or document.get("number") or document_id
                                ).strip(),
                            )
                        )
        return links

    def _list(self, path: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        offset = 0
        while True:
            query: dict[str, Any] = {"limit": 500, "offset": offset}
            if params:
                query.update(params)
            batch = _objects(self._connection.get(path, params=query).json())
            output.extend(batch)
            if len(batch) < 500:
                return output
            offset += len(batch)
