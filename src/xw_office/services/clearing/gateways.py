"""REST gateways used by payment clearing."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, cast

import httpx

from xw_office.services.clearing.models import (
    ClearingDuplicateKey,
    InvoiceRecord,
    ProviderTransaction,
    SevdeskTransaction,
    TransactionKind,
    money,
)
from xw_office.services.http_client import SevdeskConnection
from xw_office.services.sevdesk.payment_booking import (
    book_amount_payload,
    first_object,
    is_paid_invoice_object,
    normalize_booking_amount,
    raise_on_error_envelope,
    response_payload,
)

from xw_office.services.clearing.gateway_utils import (
    TIMEOUT,
    VIENNA as VIENNA,
    parse_datetime,
)
from xw_office.services.clearing.mollie_gateway import (
    MollieClearingGateway as MollieClearingGateway,
)

_WIX_PAYMENT_REFERENCE_KEYS = ("external_transaction_id", "wp_wix_transaction_id")
logger = logging.getLogger(__name__)


def iso_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _objects(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("objects", payload.get("data", []))
    if isinstance(raw, dict):
        return [raw]
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _wix_payment_reference_ids(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, dict):
        return ()
    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        return ()
    return tuple(
        dict.fromkeys(
            value
            for key in _WIX_PAYMENT_REFERENCE_KEYS
            if (value := str(metadata.get(key) or "").strip())
        )
    )


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
        charge_to_wix_refs: dict[str, tuple[str, ...]] = {}
        for raw in self._list("/v1/charges", bounds):
            if not raw.get("paid") or raw.get("status") != "succeeded" or raw.get("currency") != "eur":
                continue
            ref = str(raw.get("id") or "")
            intent = str(raw.get("payment_intent") or "")
            charge_to_intent[ref] = intent
            wix_refs = _wix_payment_reference_ids(raw)
            charge_to_wix_refs[ref] = wix_refs
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
                    provider_reference_ids=wix_refs,
                )
            )
        for raw in self._list(
            "/v1/refunds",
            {**bounds, "expand[]": "data.charge.payment_intent"},
        ):
            if raw.get("currency") != "eur" or raw.get("status") not in {None, "succeeded"}:
                continue
            created = parse_datetime(raw.get("created"))
            ref = str(raw.get("id") or "")
            charge = raw.get("charge")
            charge_id = str(charge.get("id") or "") if isinstance(charge, dict) else str(charge or "")
            charge_intent_value = (
                charge.get("payment_intent") if isinstance(charge, dict) else None
            )
            charge_intent = (
                str(charge_intent_value.get("id") or "")
                if isinstance(charge_intent_value, dict)
                else str(charge_intent_value or "")
            )
            intent = str(
                raw.get("payment_intent") or charge_intent or charge_to_intent.get(charge_id) or ""
            )
            if ref and created:
                refund_wix_refs = list(_wix_payment_reference_ids(raw))
                if isinstance(charge, dict):
                    refund_wix_refs.extend(_wix_payment_reference_ids(charge))
                refund_wix_refs.extend(charge_to_wix_refs.get(charge_id, ()))
                if charge_id:
                    refund_wix_refs.append(charge_id)
                out.append(
                    ProviderTransaction(
                        provider="stripe",
                        provider_ref=ref,
                        provider_order_id=intent,
                        kind=TransactionKind.REFUND,
                        amount=-money(Decimal(str(raw.get("amount") or 0)) / 100),
                        created_at=created,
                        source_id=ref,
                        provider_reference_ids=tuple(dict.fromkeys(refund_wix_refs)),
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


class WixClearingGateway:
    def __init__(self, api_key: str, site_id: str) -> None:
        self._api_key = api_key.strip()
        self._site_id = site_id.strip()
        self.last_warning = ""
        self.blocked_reference_ids: set[str] = set()
        # False when any order's payment lookup was not definitively answered;
        # payment-derived references of that run are then blocked, not mapped.
        self.lookup_complete = True
        self.incomplete_order_ids: set[str] = set()

    def available(self) -> bool:
        return bool(self._api_key and self._site_id)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._api_key, "wix-site-id": self._site_id}

    def search_orders(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        if not self.available():
            return []
        orders: list[dict[str, Any]] = []
        cursor = ""
        seen_cursors: set[str] = set()
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
                batch = payload.get("orders", []) if isinstance(payload, dict) else None
                if not isinstance(batch, list):
                    raise ValueError("Wix lieferte eine ungueltige Order-Suchseite.")
                orders.extend(item for item in batch if isinstance(item, dict))
                metadata = payload.get("metadata")
                metadata = metadata if isinstance(metadata, dict) else {}
                paging_metadata = payload.get("pagingMetadata")
                paging_metadata = paging_metadata if isinstance(paging_metadata, dict) else {}
                cursors = metadata.get("cursors")
                cursors = cursors if isinstance(cursors, dict) else {}
                paging_cursors = paging_metadata.get("cursors")
                paging_cursors = paging_cursors if isinstance(paging_cursors, dict) else {}
                cursor = str(
                    cursors.get("next")
                    or paging_cursors.get("next")
                    or paging_metadata.get("nextCursor")
                    or paging_metadata.get("next")
                    or ""
                )
                if not cursor:
                    return orders
                if cursor in seen_cursors:
                    raise RuntimeError("Wix order search returned a repeated paging cursor.")
                seen_cursors.add(cursor)

    def provider_map(self, start: datetime, end: datetime) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        self.last_warning = ""
        self.blocked_reference_ids.clear()
        self.lookup_complete = True
        self.incomplete_order_ids.clear()
        provider_references: dict[str, set[str]] = {}
        payment_references: set[str] = set()
        by_number: dict[str, dict[str, Any]] = {}
        if not self.available():
            return {}, by_number

        def add_reference(reference: str, order_number: str) -> None:
            ref = reference.strip()
            if ref and order_number:
                provider_references.setdefault(ref, set()).add(order_number)

        warnings: list[str] = []
        orders = self.search_orders(start, end)
        order_number_by_id: dict[str, str] = {}
        for order in orders:
            order_id = str(order.get("id") or "")
            order_number = str(order.get("number") or "")
            if order_number:
                by_number[order_number] = order
            if order_id and order_number:
                order_number_by_id[order_id] = order_number
                add_reference(order_id, order_number)
                checkout_id = str(order.get("checkoutId") or "")
                if checkout_id:
                    add_reference(checkout_id, order_number)

        with httpx.Client(base_url="https://www.wixapis.com/ecom/v1", headers=self._headers(), timeout=TIMEOUT) as client:
            order_ids = list(order_number_by_id)
            for offset in range(0, len(order_ids), 100):
                chunk = order_ids[offset : offset + 100]
                response = client.post("/payments/list-by-ids", json={"orderIds": chunk})
                definitive_empty: set[str] = set()
                if response.status_code == 200:
                    payload = response.json()
                    raw_transactions = (
                        payload.get("orderTransactions", [])
                        if isinstance(payload, dict)
                        else None
                    )
                    if not isinstance(raw_transactions, list):
                        warnings.append("Wix payment batch lookup returned an invalid payload.")
                        raw_transactions = []
                    transactions = raw_transactions
                else:
                    warnings.append(
                        f"Wix payment batch lookup failed with HTTP {response.status_code}; "
                        f"using individual requests for {len(chunk)} orders."
                    )
                    transactions = []
                    for order_id in chunk:
                        single = client.get(f"/payments/orders/{order_id}")
                        if single.status_code == 200:
                            payload = single.json()
                            item = (
                                payload.get("orderTransactions") or {}
                                if isinstance(payload, dict)
                                else {}
                            )
                            if isinstance(item, dict):
                                item.setdefault("orderId", order_id)
                                transactions.append(item)
                            else:
                                warnings.append(
                                    f"Wix payment lookup for order {order_id} returned an invalid payload."
                                )
                        elif single.status_code == 404:
                            definitive_empty.add(order_id)
                            warnings.append(
                                f"Wix payment lookup returned HTTP 404 (no transactions) for order {order_id}."
                            )
                        else:
                            warnings.append(
                                f"Wix payment lookup failed for order {order_id} "
                                f"with HTTP {single.status_code}."
                            )
                found_order_ids: set[str] = set()
                for transaction in transactions:
                    if not isinstance(transaction, dict):
                        continue
                    order_id = str(transaction.get("orderId") or "")
                    order_number = order_number_by_id.get(order_id, "")
                    if order_id and order_number:
                        found_order_ids.add(order_id)
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
                            ref = str(regular.get(key) or payment.get(key) or "").strip()
                            add_reference(ref, order_number)
                            if ref:
                                payment_references.add(ref)
                missing_order_ids = set(chunk) - found_order_ids - definitive_empty
                if missing_order_ids:
                    self.incomplete_order_ids.update(missing_order_ids)
                    warnings.append(
                        "Wix payment lookup returned no transactions for order(s): "
                        + ", ".join(sorted(missing_order_ids))
                        + "."
                    )

        provider_to_order: dict[str, str] = {}
        conflicts = sorted(
            reference
            for reference, order_numbers in provider_references.items()
            if len(order_numbers) > 1
        )
        for reference, order_numbers in provider_references.items():
            if len(order_numbers) == 1:
                provider_to_order[reference] = next(iter(order_numbers))
        if conflicts:
            self.blocked_reference_ids.update(conflicts)
            warnings.append(
                "Conflicting Wix provider references were removed: " + ", ".join(conflicts) + "."
            )
        if self.incomplete_order_ids:
            # A missing order could carry the same provider ID; uniqueness is unproven.
            self.lookup_complete = False
            unverified = sorted(ref for ref in payment_references if ref in provider_to_order)
            for ref in unverified:
                del provider_to_order[ref]
            self.blocked_reference_ids.update(payment_references)
            warnings.append(
                "Wix payment lookup incomplete; "
                f"{len(unverified)} payment reference(s) blocked as unverified."
            )
        if warnings:
            self.last_warning = " ".join(dict.fromkeys(warnings))
            logger.warning("Wix clearing provider map warning: %s", self.last_warning)
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
            if response.status_code == 404:
                return ""
            if response.status_code != 200:
                response.raise_for_status()
                raise RuntimeError(
                    f"Wix order lookup returned unexpected HTTP {response.status_code}."
                )
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

    def get_invoice_by_id(self, invoice_id: int) -> dict[str, Any]:
        response = self._conn.get(f"/Invoice/{int(invoice_id)}")
        try:
            payload = response.json()
        except ValueError:
            return {}
        return first_object(payload)

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
    ) -> dict[str, Any]:
        invoice_before = self.get_invoice_by_id(int(invoice_id))
        if is_paid_invoice_object(invoice_before):
            return {
                "status": "invoice_already_paid",
                "transaction_id": int(transaction_id),
                "invoice_status": str(invoice_before.get("status") or "").strip(),
            }
        if str(invoice_before.get("status") or "").strip() == "100":
            return {
                "status": "invoice_draft",
                "transaction_id": int(transaction_id),
                "invoice_status": "100",
                "warning": "sevDesk-Entwurf kann nicht gebucht werden.",
            }

        tx_before = self.get_check_account_transaction_by_id(int(transaction_id))
        tx_status_before = str(tx_before.get("status") or "").strip()
        if tx_status_before == "400":
            return {
                "status": "already_booked",
                "transaction_id": int(transaction_id),
                "tx_status": tx_status_before,
            }
        if "amount" in tx_before and tx_before.get("amount") is not None:
            transaction_amount = money(tx_before["amount"])
            requested_amount = money(amount)
            if transaction_amount != requested_amount:
                return {
                    "status": "transaction_amount_mismatch",
                    "transaction_id": int(transaction_id),
                    "tx_status": tx_status_before,
                    "warning": (
                        "sevDesk-Transaktionsbetrag stimmt nicht mit dem angeforderten "
                        "Buchungsbetrag ueberein."
                    ),
                }

        tx_account_id = str((tx_before.get("checkAccount") or {}).get("id") or "").strip()
        if tx_account_id and tx_account_id != str(int(account_id)):
            return {
                "status": "account_mismatch",
                "transaction_id": int(transaction_id),
                "tx_account_id": tx_account_id,
                "check_account_id": str(int(account_id)),
            }

        booking_ts = int(payment_date.timestamp())
        if self._bookkeeping_system_version() == "1.0":
            self._legacy_link_invoice(
                transaction_id=int(transaction_id),
                invoice_id=int(invoice_id),
                amount=amount,
                booking_date=booking_ts,
            )
        else:
            response = self._conn.put(
                f"/Invoice/{int(invoice_id)}/bookAmount",
                json=book_amount_payload(
                    amount=amount,
                    booking_date=booking_ts,
                    check_account_id=int(account_id),
                    transaction_id=int(transaction_id),
                ),
            )
            payload = response_payload(response)
            raise_on_error_envelope(payload, "sevDesk Invoice bookAmount Fehler")

        invoice_after = self.get_invoice_by_id(int(invoice_id))
        tx_after = self.get_check_account_transaction_by_id(int(transaction_id))
        tx_status_after = str(tx_after.get("status") or "").strip()

        if not is_paid_invoice_object(invoice_after):
            return {
                "status": "not_booked",
                "transaction_id": int(transaction_id),
                "invoice_status": str(invoice_after.get("status") or "").strip(),
                "tx_status": tx_status_after,
            }

        warning = ""
        if tx_status_after != "400":
            try:
                self.change_check_account_transaction_status(int(transaction_id), 400)
                tx_after = self.get_check_account_transaction_by_id(int(transaction_id))
                tx_status_after = str(tx_after.get("status") or "").strip()
            except Exception as exc:
                warning = (
                    "Rechnung wurde in sevDesk als bezahlt bestaetigt, aber der "
                    f"Transaktionsstatus konnte nicht auf 400 gesetzt werden: {exc}"
                )
                logger.warning("sevDesk post-booking transaction status update failed: %s", exc)

        result = {
            "status": "booked",
            "transaction_id": int(transaction_id),
            "invoice_status": str(invoice_after.get("status") or "").strip(),
            "tx_status": tx_status_after,
        }
        if warning:
            result["warning"] = warning
        return result

    def _legacy_link_invoice(
        self,
        *,
        transaction_id: int,
        invoice_id: int,
        amount: Decimal,
        booking_date: int,
    ) -> dict[str, Any]:
        params = {"invoiceId": int(invoice_id)}
        body = {
            "amount": normalize_booking_amount(amount),
            "date": int(booking_date),
        }
        endpoint = f"/CheckAccountTransaction/{int(transaction_id)}/linkInvoice"
        try:
            response = self._conn.put(endpoint, params=params, json=body)
        except Exception as exc:
            error_response = getattr(exc, "response", None)
            status_code = getattr(exc, "status_code", None) or getattr(
                error_response, "status_code", None
            )
            if status_code not in {405, 501}:
                raise
            response = self._conn.patch(endpoint, params=params, json=body)
        payload = response_payload(response)
        raise_on_error_envelope(payload, "sevDesk linkInvoice Fehler")
        return payload

    def _bookkeeping_system_version(self) -> str:
        if self._bookkeeping_version:
            return self._bookkeeping_version
        response = self._conn.get("/Tools/bookkeepingSystemVersion")
        payload = response.json()
        obj = payload.get("objects", payload) if isinstance(payload, dict) else {}
        if isinstance(obj, list):
            obj = obj[0] if obj else {}
        version = str(obj.get("version") or "").strip() if isinstance(obj, dict) else ""
        if not version:
            raise RuntimeError("sevDesk lieferte keine gueltige Buchhaltungssystem-Version.")
        self._bookkeeping_version = version
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
