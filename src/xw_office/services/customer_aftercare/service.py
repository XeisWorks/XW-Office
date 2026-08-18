"""Facade for Lieferkorrekturen: badges, manager-dialog listing, review-popup confirmation."""
from __future__ import annotations

from dataclasses import dataclass
import datetime
import uuid

from xw_office.core.config import AppConfig
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.repositories.customer_aftercare import CustomerAftercareRepository
from xw_office.services.customer_aftercare.inbox_service import (
    CustomerAftercareInboxService,
    InboxPollResult,
)
from xw_office.services.customer_aftercare.trigger_service import (
    CustomerAftercareTriggerService,
    TriggerRunResult,
)

#: Manager-dialog filters (spec §7): Zu prüfen / Fällig / Wartet / Erledigt / Alle.
MANAGER_FILTERS = ("zu_pruefen", "faellig", "wartet", "erledigt", "alle")

_FILTER_STATUSES: dict[str, tuple[str, ...]] = {
    "zu_pruefen": ("PENDING_REVIEW",),
    "faellig": ("TRIGGERED",),
    "wartet": ("WAITING",),
    "erledigt": ("RESOLVED",),
    "alle": ("PENDING_REVIEW", "WAITING", "TRIGGERED", "RESOLVED", "IGNORED", "CANCELLED"),
}


@dataclass(frozen=True)
class CaseTypePolicy:
    """How a confirmed case_type drives the case lifecycle (spec §2)."""

    customer_type: str  # "B2B" | "B2C" | ""
    wait_for_next_order: bool
    invoice_required: bool


#: One entry per confirmable Falltyp from the review popup (spec §4's dropdown).
#: UNKNOWN ("Sonstiges / manuell prüfen") never waits and never auto-triggers —
#: see CustomerAftercareService.confirm_case for how it's kept out of both the
#: due-date trigger and the immediate-trigger path.
_POLICIES: dict[str, CaseTypePolicy] = {
    "B2B_WRONG_DELIVERY": CaseTypePolicy("B2B", wait_for_next_order=True, invoice_required=False),
    "B2B_MISSING_ITEMS": CaseTypePolicy("B2B", wait_for_next_order=True, invoice_required=False),
    "B2C_WRONG_DELIVERY": CaseTypePolicy("B2C", wait_for_next_order=False, invoice_required=False),
    "B2B_CUSTOMER_ORDER_ERROR": CaseTypePolicy("B2B", wait_for_next_order=False, invoice_required=True),
    "UNKNOWN": CaseTypePolicy("", wait_for_next_order=False, invoice_required=False),
}


def resolve_case_policy(case_type: str) -> CaseTypePolicy:
    return _POLICIES.get(case_type, _POLICIES["UNKNOWN"])


class CustomerAftercareService:
    """Facade used by the Tagesgeschäft badges, the manager dialog and the review popup."""

    def __init__(
        self,
        repo: CustomerAftercareRepository | None,
        inbox: CustomerAftercareInboxService,
        trigger: CustomerAftercareTriggerService,
        config: AppConfig,
    ) -> None:
        self._repo = repo
        self._inbox = inbox
        self._trigger = trigger
        self._config = config

    # -- badges ---------------------------------------------------------------

    def count_pending_review(self) -> int:
        return self._repo.count_pending_review() if self._repo is not None else 0

    def count_due(self) -> int:
        return self._repo.count_due() if self._repo is not None else 0

    # -- listing ----------------------------------------------------------------

    def list_cases_for_filter(self, filter_key: str) -> list[CustomerAftercareCase]:
        if self._repo is None:
            return []
        statuses = _FILTER_STATUSES.get(filter_key, _FILTER_STATUSES["alle"])
        return self._repo.list_by_statuses(statuses)

    def get_case(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._repo.get_case(case_id) if self._repo is not None else None

    def get_items(self, case_id: uuid.UUID) -> list[CustomerAftercareItem]:
        return self._repo.get_items(case_id) if self._repo is not None else []

    # -- inbox polling ------------------------------------------------------

    def poll_inbox(self, *, allow_interactive_auth: bool = True) -> InboxPollResult:
        return self._inbox.poll_inbox(
            lookback_days=14, max_items=60, allow_interactive_auth=allow_interactive_auth
        )

    # -- trigger polling (Phase 10 wires the actual QTimer cadence) -----------

    def check_due_cases(self) -> TriggerRunResult:
        return self._trigger.check_due_cases()

    def check_new_orders_for_waiting_cases(self) -> TriggerRunResult:
        return self._trigger.check_new_orders_for_waiting_cases()

    # -- review popup (spec §4) ------------------------------------------------

    def confirm_case(
        self,
        case_id: uuid.UUID,
        *,
        case_type: str,
        courtesy: bool,
        note: str = "",
    ) -> CustomerAftercareCase | None:
        """Apply the user's confirmed/edited type + Kulanz choice from the review popup."""
        if self._repo is None:
            return None
        policy = resolve_case_policy(case_type)
        if case_type == "UNKNOWN":
            wait_for_next_order = False
            due_at: datetime.datetime | None = None
            trigger_now = False
        else:
            wait_for_next_order = policy.wait_for_next_order
            trigger_now = not wait_for_next_order
            due_at = (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=self._config.customer_aftercare.b2b.max_wait_days)
                if wait_for_next_order
                else None
            )
        return self._repo.confirm_classification(
            case_id,
            case_type=case_type,
            courtesy=courtesy,
            customer_type=policy.customer_type,
            wait_for_next_order=wait_for_next_order,
            due_at=due_at,
            trigger_now=trigger_now,
            trigger_reason="IMMEDIATE" if trigger_now else "",
            invoice_required=policy.invoice_required,
            note=note,
        )

    def ignore_case(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._repo.mark_ignored(case_id) if self._repo is not None else None

    # -- manual manager-dialog actions -----------------------------------------

    def mark_resolved(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._repo.mark_resolved(case_id) if self._repo is not None else None

    def mark_cancelled(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._repo.mark_cancelled(case_id) if self._repo is not None else None

    def mark_invoice_skipped(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._repo.mark_invoice_skipped(case_id) if self._repo is not None else None
