"""REST gateways used by payment clearing."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, cast
from zoneinfo import ZoneInfo

import httpx

from xw_studio.services.clearing.models import (
    ClearingDuplicateKey,
    InvoiceRecord,
    ProviderTransaction,
    SevdeskTransaction,
    TransactionKind,
    money,
)
from xw_studio.services.http_client import SevdeskConnection

VIENNA = ZoneInfo("Europe/Vienna")
TIMEOUT = httpx.Timeout(45.0, connect=10.0)


def iso_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        raw = int(value)
        if raw >= 10**12:
            raw //= 1000
        dt = datetime.fromtimestamp(raw, tz=timezone.utc)
    elif isinstance(value, str) and value.isdigit():
        raw = int(value)
        if raw >= 10**12:
            raw //= 1000
        dt = datetime.fromtimestamp(raw, tz=timezone.utc)
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(VIENNA)


def _objects(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("objects", payload.get("data", []))
    if isinstance(raw, dict):
        return [raw]
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


class StripeClearingGateway:
    def __init__(self, secret_key: str) -> None:
        self._key = secret_key.strip()

    def available(self) -> bool:
        return bool(self._key)

    def _list(self, path: str, params: dict[str, Any]) -> Iterable[dict[str, Any]]:
        cursor = ""
        with httpx.Client(base_url="https://api.stripe.com", auth=(self._key, ""), timeout=TIMEOUT) as client:
            while True:
                page_params = dict(params)
                if cursor:
                    page_params["starting_after"] = cursor
                response = client.get(path, params=page_params)
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data", [])
                if not isinstance(data, list):
                    return
                for item in data:
                    if isinstance(item, dict):
                        yield item
                if not payload.get("has_more") or not data:
                    return
                cursor = str(data[-1].get("id") or "")

    def fetch(self, start: datetime, end: datetime) -> list[ProviderTransaction]:
        if not self.available():
            return []
        bounds = {"limit": 100, "created[gte]": int(start.timestamp()), "created[lt]": int(end.timestamp())}
        out: list[ProviderTransaction] = []
        charge_to_intent: dict[str, str] = {}
        for raw in self._list("/v1/charges", {**bounds, "expand[]": "data.balance_transaction"}):
            if not raw.get("paid") or raw.get("status") != "succeeded" or raw.get("currency") != "eur":
                continue
            ref = str(raw.get("id") or "")
            intent = str(raw.get("payment_intent") or "")
            charge_to_intent[ref] = intent
            billing = cast(
                dict[str, Any],
                raw.get("billing_details") if isinstance(raw.get("billing_details"), dict) else {},
            )
            created = parse_datetime(raw.get("created"))
            if not ref or created is None:
                continue
            name = str(billing.get("name") or "").strip()
            email = str(raw.get("receipt_email") or billing.get("email") or "").strip()
            out.append(
                ProviderTransaction(
                    provider="stripe",
                    provider_ref=ref,
                    provider_order_id=intent,
                    kind=TransactionKind.PAYMENT,
                    amount=money(Decimal(str(raw.get("amount") or 0)) / 100),
                    created_at=created,
                    customer=name or email,
                    email=email,
                    source_id=ref,
                )
            )
        for raw in self._list("/v1/refunds", {**bounds, "expand[]": "data.charge"}):
            if raw.get("currency") != "eur" or raw.get("status") not in {None, "succeeded"}:
                continue
            created = parse_datetime(raw.get("created"))
            ref = str(raw.get("id") or "")
            charge = raw.get("charge")
            charge_id = str(charge.get("id") or "") if isinstance(charge, dict) else str(charge or "")
            intent = str(raw.get("payment_intent") or charge_to_intent.get(charge_id) or "")
            if ref and created:
                out.append(
                    ProviderTransaction(
                        provider="stripe",
                        provider_ref=ref,
                        provider_order_id=intent,
                        kind=TransactionKind.REFUND,
                        amount=-money(Decimal(str(raw.get("amount") or 0)) / 100),
                        created_at=created,
                        source_id=ref,
                    )
                )
        for raw in self._list("/v1/payouts", bounds):
            if raw.get("currency") != "eur" or raw.get("status") != "paid":
                continue
            created = parse_datetime(raw.get("created"))
            ref = str(raw.get("id") or "")
            if ref and created:
                out.append(
                    ProviderTransaction(
                        provider="stripe",
                        provider_ref=ref,
                        kind=TransactionKind.PAYOUT,
                        amount=-money(Decimal(str(raw.get("amount") or 0)) / 100),
                        created_at=created,
                        source_id=ref,
                        payout_start=created,
                        payout_end=parse_datetime(raw.get("arrival_date")) or created,
                    )
                )
        return out


class MollieClearingGateway:
    def __init__(self, access_token: str) -> None:
        self._token = access_token.strip()

    def available(self) -> bool:
        return bool(self._token)

    def _list(self, path: str, embedded_key: str) -> Iterable[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self._token}"}
        next_url: str | None = path
        params: dict[str, Any] | None = {"limit": 250}
        with httpx.Client(base_url="https://api.mollie.com/v2", headers=headers, timeout=TIMEOUT) as client:
            while next_url:
                response = client.get(next_url, params=params)
                response.raise_for_status()
                payload = response.json()
                batch = (payload.get("_embedded") or {}).get(embedded_key, [])
                for item in batch if isinstance(batch, list) else []:
                    if isinstance(item, dict):
                        yield item
                next_url = ((payload.get("_links") or {}).get("next") or {}).get("href")
                params = None

    @staticmethod
    def _amount(raw: object) -> Decimal:
        if not isinstance(raw, dict) or str(raw.get("currency") or "").upper() != "EUR":
            return Decimal("0.00")
        return money(raw.get("value"))

    def fetch(self, start: datetime, end: datetime) -> list[ProviderTransaction]:
        if not self.available():
            return []
        headers = {"Authorization": f"Bearer {self._token}"}
        out: list[ProviderTransaction] = []
        with httpx.Client(base_url="https://api.mollie.com/v2", headers=headers, timeout=TIMEOUT) as client:
            for raw in self._list("/orders", "orders"):
                created = parse_datetime(raw.get("paidAt") or raw.get("createdAt"))
                if created is None or not start <= created < end or str(raw.get("status") or "").lower() != "paid":
                    continue
                order_id = str(raw.get("id") or "")
                details_response = client.get(f"/orders/{order_id}", params={"embed": "payments"})
                details_response.raise_for_status()
                details = details_response.json()
                amount = self._amount(details.get("amount") or raw.get("amount"))
                billing = cast(
                    dict[str, Any],
                    details.get("billingAddress")
                    if isinstance(details.get("billingAddress"), dict)
                    else {},
                )
                first = str(billing.get("givenName") or "").strip()
                last = str(billing.get("familyName") or "").strip()
                customer = " ".join(part for part in (first, last) if part)
                email = str(billing.get("email") or "").strip()
                order_number = str(details.get("orderNumber") or raw.get("orderNumber") or "")
                payments = ((details.get("_embedded") or {}).get("payments") or [])
                paid = [p for p in payments if isinstance(p, dict) and p.get("status") == "paid"] or [{}]
                for payment in paid:
                    ref = str(payment.get("id") or order_id)
                    out.append(
                        ProviderTransaction(
                            provider="mollie",
                            provider_ref=ref,
                            provider_order_id=order_id,
                            order_number=order_number,
                            kind=TransactionKind.PAYMENT,
                            amount=amount,
                            created_at=created,
                            customer=customer or email,
                            email=email,
                            source_id=ref,
                        )
                    )
            for raw in self._list("/refunds", "refunds"):
                created = parse_datetime(raw.get("createdAt"))
                if (
                    created is None
                    or not start <= created < end
                    or str(raw.get("status") or "").lower() != "refunded"
                ):
                    continue
                ref = str(raw.get("id") or "")
                if ref:
                    out.append(
                        ProviderTransaction(
                            provider="mollie",
                            provider_ref=ref,
                            provider_order_id=str(raw.get("orderId") or raw.get("paymentId") or ""),
                            kind=TransactionKind.REFUND,
                            amount=-self._amount(raw.get("amount")),
                            created_at=created,
                            source_id=ref,
                        )
                    )
            try:
                settlements = list(self._list("/settlements", "settlements"))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    settlements = []
                else:
                    raise
            for raw in settlements:
                created = parse_datetime(raw.get("settledAt") or raw.get("createdAt"))
                if created is None or not start <= created < end:
                    continue
                ref = str(raw.get("reference") or raw.get("id") or "")
                out.append(
                    ProviderTransaction(
                        provider="mollie",
                        provider_ref=ref,
                        kind=TransactionKind.PAYOUT,
                        amount=-self._amount(raw.get("amount")),
                        created_at=created,
                        source_id=str(raw.get("id") or ref),
                        payout_start=parse_datetime(raw.get("createdAt")) or created,
                        payout_end=created,
                    )
                )
        return out


class WixClearingGateway:
    def __init__(self, api_key: str, site_id: str) -> None:
        self._api_key = api_key.strip()
        self._site_id = site_id.strip()

    def available(self) -> bool:
        return bool(self._api_key and self._site_id)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._api_key, "wix-site-id": self._site_id}

    def search_orders(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        if not self.available():
            return []
        orders: list[dict[str, Any]] = []
        cursor = ""
        with httpx.Client(base_url="https://www.wixapis.com/ecom/v1", headers=self._headers(), timeout=TIMEOUT) as client:
            while True:
                paging: dict[str, object] = {"limit": 100}
                if cursor:
                    paging["cursor"] = cursor
                body = {
                    "search": {
                        "filter": {
                            "$and": [
                                {"createdDate": {"$gte": iso_utc(start)}},
                                {"createdDate": {"$lt": iso_utc(end)}},
                            ]
                        },
                        "sort": [{"fieldName": "createdDate", "order": "ASC"}],
                        "cursorPaging": paging,
                    }
                }
                response = client.post("/orders/search", json=body)
                response.raise_for_status()
                payload = response.json()
                batch = payload.get("orders", [])
                orders.extend(item for item in batch if isinstance(item, dict))
                cursor = str(((payload.get("metadata") or {}).get("cursors") or {}).get("next") or "")
                if not cursor:
                    return orders

    def provider_map(self, start: datetime, end: datetime) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        provider_to_order: dict[str, str] = {}
        by_number: dict[str, dict[str, Any]] = {}
        if not self.available():
            return provider_to_order, by_number
        orders = self.search_orders(start, end)
        order_number_by_id: dict[str, str] = {}
        for order in orders:
            order_id = str(order.get("id") or "")
            order_number = str(order.get("number") or "")
            if order_number:
                by_number[order_number] = order
            if order_id and order_number:
                order_number_by_id[order_id] = order_number
                provider_to_order[order_id] = order_number
                checkout_id = str(order.get("checkoutId") or "")
                if checkout_id:
                    provider_to_order[checkout_id] = order_number

        with httpx.Client(base_url="https://www.wixapis.com/ecom/v1", headers=self._headers(), timeout=TIMEOUT) as client:
            order_ids = list(order_number_by_id)
            for offset in range(0, len(order_ids), 100):
                chunk = order_ids[offset : offset + 100]
                response = client.post("/payments/list-by-ids", json={"orderIds": chunk})
                if response.status_code == 200:
                    transactions = response.json().get("orderTransactions") or []
                else:
                    transactions = []
                    for order_id in chunk:
                        single = client.get(f"/payments/orders/{order_id}")
                        if single.status_code == 200:
                            item = single.json().get("orderTransactions") or {}
                            if isinstance(item, dict):
                                transactions.append(item)
                for transaction in transactions:
                    if not isinstance(transaction, dict):
                        continue
                    order_id = str(transaction.get("orderId") or "")
                    order_number = order_number_by_id.get(order_id, "")
                    payments = transaction.get("payments") or []
                    for payment in payments if isinstance(payments, list) else []:
                        if not isinstance(payment, dict):
                            continue
                        regular = cast(
                            dict[str, Any],
                            payment.get("regularPaymentDetails")
                            if isinstance(payment.get("regularPaymentDetails"), dict)
                            else {},
                        )
                        for key in ("providerTransactionId", "gatewayTransactionId", "paymentOrderId"):
                            ref = str(regular.get(key) or payment.get(key) or "")
                            if ref and order_number:
                                provider_to_order[ref] = order_number
        return provider_to_order, by_number

    def resolve_order_number(self, reference: str) -> str:
        """Resolve a Wix order UUID that lies outside the search window."""
        ref = reference.strip()
        if not ref or not self.available():
            return ""
        with httpx.Client(
            base_url="https://www.wixapis.com/ecom/v1",
            headers=self._headers(),
            timeout=TIMEOUT,
        ) as client:
            response = client.get(f"/orders/{ref}")
            if response.status_code != 200:
                return ""
            payload = response.json()
            order = payload.get("order", payload)
            if not isinstance(order, dict):
                return ""
            return str(order.get("number") or "")


class SevdeskClearingGateway:
    def __init__(self, connection: SevdeskConnection) -> None:
        self._conn = connection
        self._bookkeeping_version: str | None = None

    def _all(self, resource: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            response = self._conn.get(f"/{resource}", params={"limit": 500, "offset": offset, **(params or {})})
            batch = _objects(response.json())
            out.extend(batch)
            if len(batch) < 500:
                return out
            offset += len(batch)

    def account_ids(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for raw in self._all("CheckAccount"):
            name = str(raw.get("name") or "").strip().casefold()
            if name in {"stripe", "mollie"}:
                result[name] = int(raw["id"])
        return result

    def invoices(self, start: datetime, end: datetime) -> list[InvoiceRecord]:
        params = {
            "startDate": int(start.timestamp()),
            "endDate": int(end.timestamp()),
            "format": "seconds",
        }
        rows = self._all("Invoice", params)
        if not rows:
            rows = self._all("Invoice", {"startDate": start.isoformat(), "endDate": end.isoformat()})
        out: list[InvoiceRecord] = []
        for raw in rows:
            reference = ""
            for key in ("reference", "customerInternalNote", "customerInternalNoteText", "referenceNumber", "orderNumber"):
                reference = str(raw.get(key) or "").strip()
                if reference:
                    break
            contact = cast(
                dict[str, Any],
                raw.get("contact") if isinstance(raw.get("contact"), dict) else {},
            )
            customer = str(contact.get("name") or "").strip()
            out.append(
                InvoiceRecord(
                    invoice_id=int(raw["id"]),
                    invoice_number=str(raw.get("invoiceNumber") or raw.get("number") or ""),
                    reference=reference,
                    amount=money(raw.get("sumGross") or raw.get("sum")),
                    status=int(raw.get("status") or 0),
                    customer=customer,
                )
            )
        return out

    def find_invoice(self, invoice_number: str) -> InvoiceRecord | None:
        rows = self._all("Invoice", {"invoiceNumber": invoice_number})
        if not rows:
            return None
        raw = rows[0]
        reference = ""
        for key in ("reference", "customerInternalNote", "customerInternalNoteText", "referenceNumber", "orderNumber"):
            reference = str(raw.get(key) or "").strip()
            if reference:
                break
        return InvoiceRecord(
            invoice_id=int(raw["id"]),
            invoice_number=str(raw.get("invoiceNumber") or ""),
            reference=reference,
            amount=money(raw.get("sumGross") or raw.get("sum")),
            status=int(raw.get("status") or 0),
            customer=str((raw.get("contact") or {}).get("name") or "") if isinstance(raw.get("contact"), dict) else "",
        )

    def find_transaction_by_duplicate_key(
        self,
        account_id: int,
        duplicate_key: ClearingDuplicateKey,
        value_date: datetime,
    ) -> SevdeskTransaction | None:
        for row in self.transactions(
            account_id,
            value_date - timedelta(days=2),
            value_date + timedelta(days=3),
        ):
            if transaction_duplicate_key(row).as_tuple() == duplicate_key.as_tuple():
                return row
        return None

    def transactions(self, account_id: int, start: datetime, end: datetime) -> list[SevdeskTransaction]:
        rows = self._all(
            "CheckAccountTransaction",
            {
                "checkAccount[id]": account_id,
                "checkAccount[objectName]": "CheckAccount",
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
            },
        )
        out: list[SevdeskTransaction] = []
        for raw in rows:
            value_date = parse_datetime(raw.get("valueDate") or raw.get("date"))
            if value_date is None:
                continue
            out.append(
                SevdeskTransaction(
                    transaction_id=int(raw["id"]),
                    account_id=account_id,
                    amount=money(raw.get("amount")),
                    value_date=value_date,
                    purpose=str(raw.get("paymtPurpose") or ""),
                    status=int(raw.get("status") or 0),
                )
            )
        return out

    def get_check_account_transaction_by_id(self, transaction_id: int) -> dict[str, Any]:
        response = self._conn.get(f"/CheckAccountTransaction/{int(transaction_id)}")
        payload = response.json() if response.content else {}
        if isinstance(payload, dict):
            objects = payload.get("objects", payload)
            if isinstance(objects, list):
                return next((item for item in objects if isinstance(item, dict)), {})
            if isinstance(objects, dict):
                return objects
        if isinstance(payload, list):
            return next((item for item in payload if isinstance(item, dict)), {})
        return {}

    def change_check_account_transaction_status(self, transaction_id: int, status: int) -> dict[str, Any]:
        response = self._conn.put(
            f"/CheckAccountTransaction/{int(transaction_id)}",
            json={"status": int(status)},
        )
        return response.json() if response.content else {}

    def create_transaction(
        self,
        *,
        account_id: int,
        amount: Decimal,
        value_date: datetime,
        payee: str,
        purpose: str,
    ) -> int:
        payload = {
            "valueDate": value_date.isoformat(),
            "entryDate": value_date.isoformat(),
            "checkAccount": {"id": account_id, "objectName": "CheckAccount"},
            "amount": float(amount),
            "status": 100,
            "payeePayerName": payee,
            "paymtPurpose": purpose,
        }
        response = self._conn.post("/CheckAccountTransaction", json=payload)
        objects = _objects(response.json())
        if not objects:
            raise RuntimeError("sevDesk lieferte keine Transaktions-ID")
        return int(objects[0]["id"])

    def book_invoice(
        self,
        *,
        invoice_id: int,
        amount: Decimal,
        payment_date: datetime,
        account_id: int,
        transaction_id: int,
    ) -> None:
        if self._bookkeeping_system_version() == "1.0":
            self._conn.put(
                f"/CheckAccountTransaction/{transaction_id}/linkInvoice",
                params={"invoiceId": invoice_id},
                json={"amount": float(amount), "date": int(payment_date.timestamp())},
            )
            return
        self._conn.put(
            f"/Invoice/{invoice_id}/bookAmount",
            json={
                "amount": float(amount),
                "date": int(payment_date.timestamp()),
                "type": "FULL_PAYMENT",
                "checkAccount": {"id": account_id, "objectName": "CheckAccount"},
                "checkAccountTransaction": {
                    "id": transaction_id,
                    "objectName": "CheckAccountTransaction",
                },
                "createFeed": False,
            },
        )

    def _bookkeeping_system_version(self) -> str:
        if self._bookkeeping_version:
            return self._bookkeeping_version
        try:
            response = self._conn.get("/Tools/bookkeepingSystemVersion")
            payload = response.json()
            obj = payload.get("objects", payload) if isinstance(payload, dict) else {}
            if isinstance(obj, list):
                obj = obj[0] if obj else {}
            version = str(obj.get("version") or "") if isinstance(obj, dict) else ""
        except Exception:
            version = "1.0"
        self._bookkeeping_version = version or "1.0"
        return self._bookkeeping_version


_PURPOSE_REF = re.compile(r"(?:stripe|mollie|payout):([^|\s]+)", re.IGNORECASE)
_PROVIDER_REF = re.compile(r"(stripe|mollie):([^|\s]+)", re.IGNORECASE)
_PAYOUT_REF = re.compile(r"payout:([^|\s]+)", re.IGNORECASE)


def purpose_provider_ref(purpose: str) -> str:
    match = _PURPOSE_REF.search(purpose or "")
    return match.group(1).strip() if match else ""


def transaction_duplicate_key(row: SevdeskTransaction) -> ClearingDuplicateKey:
    purpose = row.purpose or ""
    provider = ""
    provider_ref = ""
    kind = TransactionKind.PAYMENT
    payout = _PAYOUT_REF.search(purpose)
    if payout:
        provider = "payout"
        provider_ref = payout.group(1).strip()
        kind = TransactionKind.PAYOUT
    else:
        provider_match = _PROVIDER_REF.search(purpose)
        if provider_match:
            provider = provider_match.group(1).casefold().strip()
            provider_ref = provider_match.group(2).strip()
        upper = purpose.upper()
        if "REFUND" in upper:
            kind = TransactionKind.REFUND
    return ClearingDuplicateKey(
        kind=kind,
        provider=provider,
        provider_ref=provider_ref,
        value_date=row.value_date.date().isoformat(),
        amount=money(row.amount),
    )
