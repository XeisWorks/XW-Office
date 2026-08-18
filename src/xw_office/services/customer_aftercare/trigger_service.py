"""Trigger polling: 20-day expiry + new-order matching for WAITING cases (spec §5/§6).

Matching priority (spec §5): Wix ``buyerInfo.contactId`` first, normalized
email as fallback, name is *never* used as a sole auto-trigger signal — a
WAITING case without a contact id or email is simply skipped by
``check_new_orders_for_waiting_cases`` (acceptance MATCH-01).
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime
import logging

from xw_office.repositories.customer_aftercare import CustomerAftercareRepository
from xw_office.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TriggerRunResult:
    checked: int
    triggered: int


class CustomerAftercareTriggerService:
    """Move WAITING cases to TRIGGERED: new order from the same customer, or 20 days elapsed."""

    def __init__(
        self,
        repo: CustomerAftercareRepository | None,
        wix_orders: WixOrdersClient | None,
    ) -> None:
        self._repo = repo
        self._wix_orders = wix_orders

    def check_due_cases(self, *, now: datetime.datetime | None = None) -> TriggerRunResult:
        """spec §5/§6: ``due_at`` reached without a new order -> TRIGGERED (MAX_WAIT_EXPIRED)."""
        if self._repo is None:
            return TriggerRunResult(checked=0, triggered=0)
        now = now or datetime.datetime.now(datetime.timezone.utc)
        due_cases = self._repo.list_due_waiting_cases(now=now)
        triggered = 0
        for case in due_cases:
            result = self._repo.try_transition_waiting_to_triggered(case.id, reason="MAX_WAIT_EXPIRED")
            if result is not None:
                triggered += 1
        return TriggerRunResult(checked=len(due_cases), triggered=triggered)

    def check_new_orders_for_waiting_cases(self) -> TriggerRunResult:
        """spec §5: a new order from the same B2B customer -> TRIGGERED (NEW_ORDER)."""
        if self._repo is None or self._wix_orders is None:
            return TriggerRunResult(checked=0, triggered=0)
        waiting = self._repo.list_waiting_cases()
        checked = 0
        triggered = 0
        for case in waiting:
            if not case.wix_contact_id and not case.customer_email:
                continue  # MATCH-01: name alone never auto-triggers
            checked += 1
            since = case.source_order_created_at or case.created_at
            try:
                orders = self._wix_orders.find_recent_orders_by_contact_or_email(
                    contact_id=case.wix_contact_id,
                    email=case.customer_email,
                    since=since,
                    exclude_order_id=case.source_wix_order_id,
                )
            except Exception as exc:  # noqa: BLE001 - matching must never crash the polling job.
                logger.warning("Lieferkorrektur Wix-Bestellabgleich fehlgeschlagen fuer %s: %s", case.id, exc)
                continue
            if not orders:
                continue
            newest = orders[0]  # find_recent_orders_by_contact_or_email preserves createdDate DESC
            result = self._repo.try_transition_waiting_to_triggered(
                case.id,
                reason="NEW_ORDER",
                trigger_wix_order_id=str(newest.get("id") or ""),
                trigger_wix_order_number=str(newest.get("number") or ""),
            )
            if result is not None:
                triggered += 1
        return TriggerRunResult(checked=checked, triggered=triggered)
