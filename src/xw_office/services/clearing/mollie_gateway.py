"""Mollie payment clearing gateway."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, cast

import httpx

from xw_office.services.clearing.gateway_utils import TIMEOUT, parse_datetime
from xw_office.services.clearing.mollie_cache import MolliePaymentCache, SettingsRepository
from xw_office.services.clearing.models import ProviderTransaction, TransactionKind, money

logger = logging.getLogger(__name__)


class MollieClearingGateway:
    def __init__(
        self,
        access_token: str,
        settings_repo: SettingsRepository | None = None,
    ) -> None:
        self._token = access_token.strip()
        self._settings_repo = settings_repo
        self.last_warning: str = ""

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

    @staticmethod
    def _link_resource_id(raw: dict[str, Any], key: str) -> str:
        links = raw.get("_links") if isinstance(raw.get("_links"), dict) else {}
        link = links.get(key) if isinstance(links, dict) else None
        href = str(link.get("href") or "").strip() if isinstance(link, dict) else ""
        return href.rstrip("/").rsplit("/", 1)[-1] if href else ""

    @staticmethod
    def _payment_snapshot(raw: dict[str, Any], fetched_at: float) -> dict[str, Any]:
        billing = raw.get("billingAddress")
        billing = billing if isinstance(billing, dict) else {}
        first = str(billing.get("givenName") or "").strip()
        last = str(billing.get("familyName") or "").strip()
        customer = " ".join(part for part in (first, last) if part)
        email = str(raw.get("billingEmail") or billing.get("email") or "").strip()
        metadata = raw.get("metadata")
        wix_ref = (
            str(metadata.get("wix_transaction_id") or "").strip()
            if isinstance(metadata, dict)
            else ""
        )
        amount = raw.get("amount")
        amount_value = (
            {"currency": str(amount.get("currency") or ""), "value": str(amount.get("value") or "")}
            if isinstance(amount, dict)
            else {}
        )
        return {
            "id": str(raw.get("id") or "").strip(),
            "status": str(raw.get("status") or "").strip().lower(),
            "createdAt": str(raw.get("createdAt") or ""),
            "paidAt": str(raw.get("paidAt") or ""),
            "amount": amount_value,
            "orderId": str(raw.get("orderId") or MollieClearingGateway._link_resource_id(raw, "order")),
            "orderNumber": str(raw.get("orderNumber") or ""),
            "customer": customer,
            "email": email,
            "wixReference": wix_ref,
            "fetched_at": fetched_at,
        }

    def _payment_pages(
        self,
        client: httpx.Client,
        known_newest_id: str = "",
    ) -> Iterable[dict[str, Any]]:
        next_url: str | None = "/payments"
        params: dict[str, Any] | None = {"limit": 250}
        while next_url:
            response = client.get(next_url, params=params)
            response.raise_for_status()
            payload = response.json()
            embedded = payload.get("_embedded") if isinstance(payload, dict) else None
            batch = embedded.get("payments") if isinstance(embedded, dict) else None
            if not isinstance(batch, list):
                raise ValueError("Mollie lieferte eine ungueltige Payment-Seite.")
            page = [item for item in batch if isinstance(item, dict)]
            yield from page
            if known_newest_id and any(
                str(item.get("id") or "") == known_newest_id for item in page
            ):
                return
            links = payload.get("_links") if isinstance(payload, dict) else None
            next_link = links.get("next") if isinstance(links, dict) else None
            next_url = (
                str(next_link.get("href") or "").strip()
                if isinstance(next_link, dict)
                else ""
            ) or None
            params = None

    @staticmethod
    def _cached_newest_id(payments: dict[str, dict[str, Any]]) -> str:
        newest_id = ""
        newest_created: datetime | None = None
        for payment_id, payment in payments.items():
            created = parse_datetime(payment.get("createdAt"))
            if created is not None and (newest_created is None or created > newest_created):
                newest_id = payment_id
                newest_created = created
        return newest_id

    @staticmethod
    def _preserve_enrichment(
        snapshot: dict[str, Any],
        cached: dict[str, Any],
    ) -> dict[str, Any]:
        for key in ("orderNumber", "customer", "email", "wixReference"):
            if not snapshot.get(key) and cached.get(key):
                snapshot[key] = cached[key]
        return snapshot

    @staticmethod
    def _unresolved_payment(payment: dict[str, Any]) -> bool:
        return str(payment.get("status") or "").lower() not in {
            "paid",
            "canceled",
            "cancelled",
            "expired",
            "failed",
        }

    def _refund_order_details(
        self,
        client: httpx.Client,
        raw: dict[str, Any],
    ) -> tuple[str, str]:
        order_id = str(raw.get("orderId") or self._link_resource_id(raw, "order") or "").strip()
        payment_id = str(raw.get("paymentId") or self._link_resource_id(raw, "payment") or "").strip()
        order_number = str(raw.get("orderNumber") or "").strip()
        if order_number:
            return order_number, order_id or payment_id
        if not order_id and payment_id:
            payment_response = client.get(f"/payments/{payment_id}")
            if payment_response.status_code != 404:
                if payment_response.status_code != 200:
                    payment_response.raise_for_status()
                    raise RuntimeError(
                        "Mollie payment lookup returned unexpected "
                        f"HTTP {payment_response.status_code}."
                    )
                payment = payment_response.json()
                if isinstance(payment, dict):
                    order_number = str(payment.get("orderNumber") or "").strip()
                    order_id = str(
                        payment.get("orderId") or self._link_resource_id(payment, "order") or ""
                    ).strip()
                    if order_number:
                        return order_number, order_id or payment_id
        if order_id:
            order_response = client.get(f"/orders/{order_id}")
            if order_response.status_code != 404:
                if order_response.status_code != 200:
                    order_response.raise_for_status()
                    raise RuntimeError(
                        f"Mollie order lookup returned unexpected HTTP {order_response.status_code}."
                    )
                order = order_response.json()
                if isinstance(order, dict):
                    order_number = str(order.get("orderNumber") or "").strip()
                    if order_number:
                        return order_number, order_id
        return "", order_id or payment_id

    def fetch(self, start: datetime, end: datetime) -> list[ProviderTransaction]:
        self.last_warning = ""
        if not self.available():
            return []
        headers = {"Authorization": f"Bearer {self._token}"}
        out: list[ProviderTransaction] = []
        order_cache: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        with httpx.Client(base_url="https://api.mollie.com/v2", headers=headers, timeout=TIMEOUT) as client:
            payment_cache = (
                MolliePaymentCache(self._settings_repo, self._token)
                if self._settings_repo is not None
                else None
            )
            try:
                cached_state = payment_cache.read() if payment_cache is not None else None
            except Exception as exc:
                self.last_warning = f"Mollie-Zahlungscache konnte nicht gelesen werden: {exc}"
                raise
            cached_payments = (
                cast(dict[str, dict[str, Any]], cached_state["payments"])
                if cached_state is not None
                else {}
            )
            fetch_started_at = time.time()
            full_refresh = (
                payment_cache is None
                or cached_state is None
                or fetch_started_at - float(cached_state.get("full_refresh_at", 0)) >= 24 * 60 * 60
            )
            newest_id = "" if full_refresh else self._cached_newest_id(cached_payments)
            raw_payments = (
                self._payment_pages(client, newest_id)
                if payment_cache is not None
                else self._list("/payments", "payments")
            )
            payment_updates: dict[str, dict[str, Any]] = {}
            refreshed_from_list: set[str] = set()
            for raw in raw_payments:
                payment_id = str(raw.get("id") or "").strip()
                if not payment_id:
                    if str(raw.get("status") or "").lower() == "paid":
                        warning = "Bezahltes Mollie-Payment ohne ID ausgelassen."
                        warnings.append(warning)
                        logger.warning("%s", warning)
                    continue
                cached_payment = cached_payments.get(payment_id)
                if not full_refresh and cached_payment is not None:
                    if self._unresolved_payment(cached_payment):
                        # The list page is a fresh read; no second GET needed.
                        payment_updates[payment_id] = self._preserve_enrichment(
                            self._payment_snapshot(raw, fetch_started_at),
                            cached_payment,
                        )
                        refreshed_from_list.add(payment_id)
                    continue
                payment_updates[payment_id] = self._payment_snapshot(raw, fetch_started_at)

            if payment_cache is not None:
                for payment_id, cached_payment in cached_payments.items():
                    if (
                        not self._unresolved_payment(cached_payment)
                        or payment_id in refreshed_from_list
                    ):
                        continue
                    response = client.get(f"/payments/{payment_id}")
                    response.raise_for_status()
                    current_payment = response.json()
                    if not isinstance(current_payment, dict):
                        raise ValueError(f"Mollie-Payment {payment_id} ist ungueltig.")
                    current_payment.setdefault("id", payment_id)
                    payment_updates[payment_id] = self._preserve_enrichment(
                        self._payment_snapshot(current_payment, fetch_started_at),
                        cached_payment,
                    )
                try:
                    cached_state = payment_cache.merge(
                        payment_updates,
                        full_refresh_at=fetch_started_at if full_refresh else None,
                    )
                except Exception as exc:
                    self.last_warning = f"Mollie-Zahlungscache konnte nicht aktualisiert werden: {exc}"
                    raise
                payments_to_read = cast(
                    dict[str, dict[str, Any]], cached_state["payments"]
                )
            else:
                payments_to_read = payment_updates

            enriched_updates: dict[str, dict[str, Any]] = {}
            for ref, raw in payments_to_read.items():
                if str(raw.get("status") or "").lower() != "paid":
                    continue
                created = parse_datetime(raw.get("paidAt"))
                ref = str(raw.get("id") or "").strip()
                if created is None:
                    warning = f"Bezahltes Mollie-Payment {ref or '(ohne ID)'} ohne gueltiges paidAt ausgelassen."
                    warnings.append(warning)
                    logger.warning("%s", warning)
                    continue
                if not start <= created < end:
                    continue
                raw_amount = raw.get("amount")
                if (
                    not isinstance(raw_amount, dict)
                    or str(raw_amount.get("currency") or "").upper() != "EUR"
                ):
                    continue
                amount = self._amount(raw_amount)
                if not ref or amount <= 0:
                    warning = (
                        f"Bezahltes Mollie-Payment {ref or '(ohne ID)'} ohne ID oder "
                        "positiven EUR-Betrag ausgelassen."
                    )
                    warnings.append(warning)
                    logger.warning("%s", warning)
                    continue
                order_id = str(raw.get("orderId") or "").strip()
                details: dict[str, Any] = {}
                customer = str(raw.get("customer") or "").strip()
                email = str(raw.get("email") or "").strip()
                order_number = str(raw.get("orderNumber") or "").strip()
                if order_id and (not order_number or not customer or not email):
                    if order_id not in order_cache:
                        response = client.get(f"/orders/{order_id}")
                        response.raise_for_status()
                        order = response.json()
                        order_cache[order_id] = order if isinstance(order, dict) else {}
                    details = order_cache[order_id]
                billing = details.get("billingAddress")
                billing = billing if isinstance(billing, dict) else {}
                if not customer:
                    first = str(billing.get("givenName") or "").strip()
                    last = str(billing.get("familyName") or "").strip()
                    customer = " ".join(part for part in (first, last) if part)
                if not email:
                    email = str(billing.get("email") or "").strip()
                if not order_number:
                    order_number = str(details.get("orderNumber") or "").strip()
                customer = customer or email
                wix_ref = str(raw.get("wixReference") or "").strip()
                if payment_cache is not None and (
                    customer != str(raw.get("customer") or "")
                    or email != str(raw.get("email") or "")
                    or order_number != str(raw.get("orderNumber") or "")
                ):
                    enriched = dict(raw)
                    enriched.update(
                        {
                            "customer": customer,
                            "email": email,
                            "orderNumber": order_number,
                            "fetched_at": max(
                                float(raw.get("fetched_at", 0)),
                                time.time(),
                            ),
                        }
                    )
                    enriched_updates[ref] = enriched
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
                        provider_reference_ids=(wix_ref,) if wix_ref else (),
                    )
                )
            if payment_cache is not None and enriched_updates:
                try:
                    payment_cache.merge(enriched_updates)
                except Exception as exc:
                    self.last_warning = f"Mollie-Zahlungscache konnte nicht aktualisiert werden: {exc}"
                    raise
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
                    order_number, provider_order_id = self._refund_order_details(client, raw)
                    out.append(
                        ProviderTransaction(
                            provider="mollie",
                            provider_ref=ref,
                            provider_order_id=provider_order_id,
                            order_number=order_number,
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
                    # Mollie payouts/settlements require an OAuth-scoped token;
                    # a plain API key returns 403 here. Surface this instead of
                    # silently dropping payouts from the clearing analysis.
                    warnings.append(
                        "Mollie-Settlements nicht abrufbar (403 - fehlende Berechtigung). "
                        "Mollie-Payouts benoetigen einen OAuth-Token, ein API-Key allein reicht nicht."
                    )
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
        if warnings:
            self.last_warning = " ".join(dict.fromkeys(warnings))
        return out
