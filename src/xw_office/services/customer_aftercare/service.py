"""Facade for Lieferkorrekturen: badges, manager-dialog listing, review-popup confirmation."""
from __future__ import annotations

from dataclasses import dataclass
import datetime
import json
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
from xw_office.services.sendungen.service import OffeneSendungenService, SendungProductLine

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
    "MANUAL_REDELIVERY": CaseTypePolicy("", wait_for_next_order=True, invoice_required=False),
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
        sendungen: OffeneSendungenService | None = None,
    ) -> None:
        self._repo = repo
        self._inbox = inbox
        self._trigger = trigger
        self._config = config
        self._sendungen = sendungen

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

    def claim_for_invoice(self, **kwargs: object) -> list[CustomerAftercareCase]:
        if self._repo is None:
            return []
        cases = self._repo.claim_for_invoice(**kwargs)  # type: ignore[arg-type]
        # A previously visible ASAP dispatch is now attached to the target
        # invoice. Remove it from the open queue immediately; the relational
        # case remains retryable until the delivery note is physically printed.
        if self._sendungen is not None:
            for case in cases:
                if case.dispatch_id:
                    try:
                        self._sendungen.mark_done(case.dispatch_id, done=True, resolve_aftercare=False)
                    except Exception:
                        pass
        return cases

    def mark_delivery_note_printed(self, case_ids: list[uuid.UUID], *, path: str = "") -> None:
        if self._repo is not None:
            self._repo.mark_delivery_note_printed(case_ids, path=path)

    # -- inbox polling ------------------------------------------------------

    def poll_inbox(self, *, allow_interactive_auth: bool = True) -> InboxPollResult:
        return self._inbox.poll_inbox(
            lookback_days=14, max_items=60, allow_interactive_auth=allow_interactive_auth
        )

    # -- trigger polling (Phase 10 wires the actual QTimer cadence) -----------

    def check_due_cases(self) -> TriggerRunResult:
        result = self._trigger.check_due_cases()
        self.ensure_asap_dispatches()
        return result

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
            existing = self._repo.get_case(case_id)
            created_at = existing.created_at if existing is not None else None
            if created_at is not None and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=datetime.timezone.utc)
            due_at = (
                (created_at or datetime.datetime.now(datetime.timezone.utc))
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

    def confirm_manual_redelivery(
        self,
        case_id: uuid.UUID,
        *,
        shipping_mode: str,
        note: str = "",
    ) -> CustomerAftercareCase | None:
        """Activate a case created from the invoice action."""
        if self._repo is None:
            return None
        immediate = str(shipping_mode or "").strip().upper() == "IMMEDIATE"
        existing = self._repo.get_case(case_id)
        if existing is None:
            return None
        try:
            address = json.loads(existing.address_lines_json or "[]")
        except (TypeError, ValueError):
            address = []
        has_address = isinstance(address, list) and any(str(line).strip() for line in address)
        if not has_address:
            if immediate:
                raise ValueError("Sofortversand ist ohne zustellfähige Lieferadresse nicht möglich")
            # Keep an editable draft in review until the address is supplied.
            return existing
        if not self._repo.get_items(case_id):
            if immediate:
                raise ValueError("Für die Nachlieferung muss mindestens eine Position ausgewählt werden")
            return existing
        created_at = existing.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=datetime.timezone.utc)
        due_at = None if immediate else (
            (created_at or datetime.datetime.now(datetime.timezone.utc))
            + datetime.timedelta(days=self._config.customer_aftercare.b2b.max_wait_days)
        )
        result = self._repo.confirm_classification(
            case_id,
            case_type="MANUAL_REDELIVERY",
            courtesy=True,
            customer_type="",
            wait_for_next_order=not immediate,
            due_at=due_at,
            trigger_now=immediate,
            trigger_reason="IMMEDIATE" if immediate else "",
            invoice_required=False,
            note=note,
            shipping_mode="IMMEDIATE" if immediate else "WAIT_NEXT_ORDER_OR_DEADLINE",
        )
        if result is not None and immediate:
            self._ensure_dispatch_for_case(result)
        return result

    def ensure_asap_dispatches(self) -> int:
        """Expose due/immediate cases in OFFENE SENDUNGEN exactly once."""
        if self._repo is None or self._sendungen is None:
            return 0
        cases = [
            case
            for case in self._repo.list_by_statuses(("TRIGGERED",))
            if case.trigger_reason in {"MAX_WAIT_EXPIRED", "IMMEDIATE"}
        ]
        created = 0
        for case in cases:
            if self._ensure_dispatch_for_case(case):
                created += 1
        return created

    def _ensure_dispatch_for_case(self, case: CustomerAftercareCase) -> bool:
        if self._repo is None or self._sendungen is None:
            return False
        dispatch_id = f"nachlieferung-{case.id}"
        if case.dispatch_id and case.dispatch_status not in {"CANCELLED", "FAILED"}:
            return False
        items = self._repo.get_items(case.id)
        products = [
            SendungProductLine(
                quantity=str(max(1, int(item.quantity or 1))),
                name=item.name or item.sku,
                sku=item.sku,
                note=item.note or "Nachlieferung – nicht verrechnen",
                free_delivery=True,
                no_return_required=True,
            )
            for item in items
            if item.role in {"MISSING_TO_SEND", "CORRECTED_ORDER_ITEM"}
        ]
        if not products:
            return False
        try:
            address = json.loads(case.address_lines_json or "[]")
        except (TypeError, ValueError):
            address = []
        address_lines = [str(line).strip() for line in address if str(line).strip()] if isinstance(address, list) else []
        subject = "Nachlieferung"
        if case.source_invoice_number:
            subject += f" {case.source_invoice_number}"
        if case.source_wix_order_number:
            subject += f" / Wix {case.source_wix_order_number}"
        note = case.note or "Kostenlose Nachlieferung – nicht verrechnen."
        self._sendungen.create_manual_case(
            case_id=dispatch_id,
            subject=subject,
            note=note,
            address_lines=address_lines,
            products=products,
        )
        self._repo.set_dispatch(case.id, dispatch_id=dispatch_id, dispatch_status="ASAP")
        return True

    def ignore_case(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._repo.mark_ignored(case_id) if self._repo is not None else None

    # -- manual manager-dialog actions -----------------------------------------

    def mark_resolved(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._repo.mark_resolved(case_id) if self._repo is not None else None

    def mark_cancelled(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._repo.mark_cancelled(case_id) if self._repo is not None else None

    def mark_invoice_skipped(self, case_id: uuid.UUID) -> CustomerAftercareCase | None:
        return self._repo.mark_invoice_skipped(case_id) if self._repo is not None else None
