"""Fail-safe B2B credit gate and manual payment-plan persistence.

The gate intentionally uses the current Wix payment status instead of the
legacy invoice-number prefix convention.  It is read-only during START: no
sevDesk invoice is booked, sent, or changed by this service.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from xw_office.core.config import B2bCreditSection
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.sevdesk.invoice_client import InvoiceSummary
from xw_office.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)

_LIMITS_KEY = "b2b_credit.customer_limits.v1"
_PLANS_KEY = "b2b_credit.payment_plans.v1"
_MONEY = Decimal("0.01")


def _money(value: object) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).replace(",", ".")).quantize(_MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _customer_key(value: object) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return " ".join(text.split())


@dataclass(frozen=True)
class B2bCreditHold:
    invoice_id: str
    invoice_number: str
    order_reference: str
    customer_name: str
    customer_key: str
    payment_status: str
    net_amount: Decimal | None
    gross_amount: Decimal | None
    limit: Decimal
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "invoice_id": self.invoice_id,
            "invoice_number": self.invoice_number,
            "order_reference": self.order_reference,
            "customer_name": self.customer_name,
            "customer_key": self.customer_key,
            "payment_status": self.payment_status,
            "net_amount": str(self.net_amount) if self.net_amount is not None else "",
            "gross_amount": str(self.gross_amount) if self.gross_amount is not None else "",
            "limit": str(self.limit),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class InstallmentPlanRow:
    sequence: int
    percent: Decimal
    amount_gross: Decimal
    send_date: date
    due_date: date


@dataclass(frozen=True)
class InstallmentPlan:
    invoice_id: str
    order_reference: str
    customer_name: str
    accepted_on: date
    rows: tuple[InstallmentPlanRow, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "order_reference": self.order_reference,
            "customer_name": self.customer_name,
            "accepted_on": self.accepted_on.isoformat(),
            "rows": [
                {
                    "sequence": row.sequence,
                    "percent": str(row.percent),
                    "amount_gross": str(row.amount_gross),
                    "send_date": row.send_date.isoformat(),
                    "due_date": row.due_date.isoformat(),
                    "state": "OPEN",
                }
                for row in self.rows
            ],
        }


class B2bCreditService:
    """Evaluate B2B invoice limits and store operator-controlled plans."""

    def __init__(
        self,
        config: B2bCreditSection,
        wix_orders: WixOrdersClient | None = None,
        settings_repo: SettingKvRepository | None = None,
    ) -> None:
        self._config = config
        self._wix = wix_orders
        self._settings = settings_repo

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled)

    @staticmethod
    def customer_key(name: object) -> str:
        return _customer_key(name)

    def _read_json(self, key: str, default: object) -> object:
        if self._settings is None:
            return default
        try:
            raw = self._settings.get_value_json(key)
            return json.loads(raw) if raw else default
        except Exception as exc:  # noqa: BLE001
            logger.warning("B2B credit settings read failed key=%s: %s", key, exc)
            return default

    def _write_json(self, key: str, payload: object) -> None:
        if self._settings is None:
            return
        self._settings.set_value_json(key, json.dumps(payload, ensure_ascii=False, sort_keys=True))

    def customer_limits(self) -> dict[str, Decimal]:
        raw = self._read_json(_LIMITS_KEY, {})
        if not isinstance(raw, dict):
            return {}
        result: dict[str, Decimal] = {}
        for key, value in raw.items():
            amount = _money(value)
            if amount is not None and amount >= Decimal("0"):
                result[_customer_key(key)] = amount
        return result

    def set_customer_limit(self, customer_name: str, limit: Decimal | float | str) -> None:
        key = _customer_key(customer_name)
        amount = _money(limit)
        if not key or amount is None or amount < Decimal("0"):
            raise ValueError("Kundenname und ein nicht-negatives Limit sind erforderlich")
        raw = self._read_json(_LIMITS_KEY, {})
        data = dict(raw) if isinstance(raw, dict) else {}
        data[key] = str(amount)
        self._write_json(_LIMITS_KEY, data)

    def limit_for(self, customer_name: str) -> Decimal:
        return self.customer_limits().get(
            _customer_key(customer_name),
            _money(self._config.default_net_limit) or Decimal("1000.00"),
        )

    def _payment_status(self, reference: str, order: dict[str, Any]) -> str:
        order_id = str(order.get("id") or "").strip()
        fetch = getattr(self._wix, "fetch_order_payment_details", None)
        if order_id and callable(fetch):
            try:
                payload = fetch(order_id)
                if isinstance(payload, dict):
                    fresh_status = str(payload.get("paymentStatus") or "").strip().upper()
                    if fresh_status:
                        return fresh_status
            except Exception as exc:  # noqa: BLE001
                logger.warning("Wix payment status failed ref=%s: %s", reference, exc)
        return str(order.get("paymentStatus") or order.get("payment_status") or "").strip().upper()

    def evaluate(self, summaries: list[InvoiceSummary]) -> list[B2bCreditHold]:
        """Return every invoice that must be held before START side effects."""
        if not self.enabled:
            return []
        holds: list[B2bCreditHold] = []
        for summary in summaries:
            net = _money(summary.sum_net)
            gross = _money(summary.sum_gross)
            if net is None:
                # The threshold is a net threshold.  Never release an invoice
                # when sevDesk did not provide a verifiable net amount.
                if self._wix is not None and str(summary.order_reference or "").strip():
                    holds.append(
                        B2bCreditHold(
                            invoice_id=str(summary.id),
                            invoice_number=str(summary.invoice_number or ""),
                            order_reference=str(summary.order_reference or ""),
                            customer_name=str(summary.contact_name or ""),
                            customer_key=_customer_key(summary.contact_name),
                            payment_status="UNKNOWN",
                            net_amount=None,
                            gross_amount=gross,
                            limit=self.limit_for(summary.contact_name),
                            reason="Netto-Betrag konnte nicht verifiziert werden",
                        )
                    )
                continue
            if net <= Decimal("0"):
                continue
            reference = str(summary.order_reference or "").strip()
            order: dict[str, Any] = {}
            if self._wix is not None and reference:
                try:
                    resolved = self._wix.resolve_order(reference)
                    if isinstance(resolved, dict):
                        order = resolved
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Wix order resolve failed ref=%s: %s", reference, exc)
            status = self._payment_status(reference, order)
            if status == "PAID":
                continue
            customer_name = str(summary.contact_name or "").strip()
            if not customer_name and order:
                customer_name = str(
                    (order.get("billingInfo") or {}).get("contactDetails", {}).get("company")
                    or (order.get("buyerInfo") or {}).get("firstName")
                    or "Unbekannter Kunde"
                ).strip()
            limit = self.limit_for(customer_name)
            if status == "NOT_PAID" and net <= limit:
                continue
            if status not in {"NOT_PAID", "PAID"} and net <= limit:
                # A missing Wix status is not enough to classify an ordinary
                # invoice as B2B, but high-value invoices stay fail-safe.
                continue
            reason = (
                f"B2B-Netto {net:.2f} EUR überschreitet Limit {limit:.2f} EUR"
                if status == "NOT_PAID"
                else "Wix paymentStatus konnte nicht sicher als PAID verifiziert werden"
            )
            holds.append(
                B2bCreditHold(
                    invoice_id=str(summary.id),
                    invoice_number=str(summary.invoice_number or ""),
                    order_reference=reference,
                    customer_name=customer_name,
                    customer_key=_customer_key(customer_name),
                    payment_status=status or "UNKNOWN",
                    net_amount=net,
                    gross_amount=gross,
                    limit=limit,
                    reason=reason,
                )
            )
        return holds

    def create_installment_plan(
        self,
        hold: B2bCreditHold,
        *,
        accepted_on: date | None = None,
    ) -> InstallmentPlan:
        """Calculate the agreed 30/35/35 schedule without creating invoices."""
        accepted = accepted_on or date.today()
        gross = hold.gross_amount or Decimal("0.00")
        first = (gross * Decimal("0.30")).quantize(_MONEY, rounding=ROUND_HALF_UP)
        second = (gross * Decimal("0.35")).quantize(_MONEY, rounding=ROUND_HALF_UP)
        third = (gross - first - second).quantize(_MONEY, rounding=ROUND_HALF_UP)
        rows = (
            InstallmentPlanRow(1, Decimal("30"), first, accepted, accepted + timedelta(days=self._config.first_due_days)),
            InstallmentPlanRow(2, Decimal("35"), second, accepted + timedelta(days=self._config.second_send_after_days), accepted + timedelta(days=self._config.second_due_after_days)),
            InstallmentPlanRow(3, Decimal("35"), third, accepted + timedelta(days=self._config.third_send_after_days), accepted + timedelta(days=self._config.third_due_after_days)),
        )
        return InstallmentPlan(
            invoice_id=hold.invoice_id,
            order_reference=hold.order_reference,
            customer_name=hold.customer_name,
            accepted_on=accepted,
            rows=rows,
        )

    @staticmethod
    def hold_from_dict(payload: dict[str, str]) -> B2bCreditHold:
        """Rehydrate a UI hold after a worker crossed the Qt thread boundary."""
        return B2bCreditHold(
            invoice_id=str(payload.get("invoice_id") or ""),
            invoice_number=str(payload.get("invoice_number") or ""),
            order_reference=str(payload.get("order_reference") or ""),
            customer_name=str(payload.get("customer_name") or ""),
            customer_key=str(payload.get("customer_key") or ""),
            payment_status=str(payload.get("payment_status") or "UNKNOWN"),
            net_amount=_money(payload.get("net_amount")),
            gross_amount=_money(payload.get("gross_amount")),
            limit=_money(payload.get("limit")) or Decimal("1000.00"),
            reason=str(payload.get("reason") or ""),
        )

    def save_plan(self, plan: InstallmentPlan) -> None:
        raw = self._read_json(_PLANS_KEY, {})
        data = dict(raw) if isinstance(raw, dict) else {}
        data[plan.invoice_id] = plan.as_dict()
        self._write_json(_PLANS_KEY, data)

    def list_plans(self) -> list[dict[str, Any]]:
        raw = self._read_json(_PLANS_KEY, {})
        if not isinstance(raw, dict):
            return []
        return [value for value in raw.values() if isinstance(value, dict)]

    def count_due_plans(self, *, on: date | None = None) -> int:
        today = on or date.today()
        count = 0
        for plan in self.list_plans():
            for row in plan.get("rows", []):
                if not isinstance(row, dict) or str(row.get("state") or "OPEN").upper() != "OPEN":
                    continue
                try:
                    if date.fromisoformat(str(row.get("due_date") or "9999-12-31")) <= today:
                        count += 1
                except ValueError:
                    continue
        return count
