"""Typed payment-clearing domain models."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum

CENT = Decimal("0.01")


def money(value: object) -> Decimal:
    """Convert API money values without binary floating-point rounding."""
    try:
        return Decimal(str(value or "0").replace(",", ".")).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


class TransactionKind(str, Enum):
    PAYMENT = "payment"
    REFUND = "refund"
    PAYOUT = "payout"
    SEPA = "sepa"


class MatchStatus(str, Enum):
    READY = "ready"
    IMPORT_ONLY = "import_only"
    REFUND_IMPORT = "refund_import"
    REFUND_REVIEW = "refund_review"
    MANUAL = "manual"
    ALREADY_BOOKED = "already_booked"
    ERROR = "error"
    BOOKED = "booked"


@dataclass(frozen=True)
class ProviderTransaction:
    provider: str
    provider_ref: str
    kind: TransactionKind
    amount: Decimal
    created_at: datetime
    customer: str = ""
    email: str = ""
    order_number: str = ""
    provider_order_id: str = ""
    source_id: str = ""
    payout_start: datetime | None = None
    payout_end: datetime | None = None

    @property
    def stable_key(self) -> str:
        return "|".join(
            (
                self.kind.value,
                self.provider.casefold(),
                self.provider_ref,
                self.created_at.date().isoformat(),
                f"{self.amount:.2f}",
            )
        )


@dataclass(frozen=True)
class InvoiceRecord:
    invoice_id: int
    invoice_number: str
    reference: str
    amount: Decimal
    status: int
    customer: str = ""

    @property
    def is_paid(self) -> bool:
        return self.status == 1000

    @property
    def is_draft(self) -> bool:
        return self.status == 100 or not self.invoice_number


@dataclass(frozen=True)
class SevdeskTransaction:
    transaction_id: int
    account_id: int
    amount: Decimal
    value_date: datetime
    purpose: str
    status: int


@dataclass(frozen=True)
class ClearingDuplicateKey:
    kind: TransactionKind
    provider: str
    provider_ref: str
    value_date: str
    amount: Decimal

    def as_tuple(self) -> tuple[str, str, str, str, Decimal]:
        return (
            self.kind.value,
            self.provider.casefold().strip(),
            self.provider_ref.strip(),
            self.value_date,
            self.amount,
        )


@dataclass(frozen=True)
class ClearingCandidate:
    candidate_id: str
    provider: str
    kind: TransactionKind
    provider_ref: str
    order_number: str
    invoice_id: int | None
    invoice_number: str
    customer: str
    amount: Decimal
    payment_date: datetime
    status: MatchStatus
    reason: str
    selected: bool
    account_id: int | None = None
    transaction_id: int | None = None
    stable_key: str = ""

    @property
    def is_bookable(self) -> bool:
        return self.status in {MatchStatus.READY, MatchStatus.IMPORT_ONLY, MatchStatus.REFUND_IMPORT}

    def with_manual_invoice(self, invoice: InvoiceRecord) -> ClearingCandidate:
        status = MatchStatus.READY if self.kind in {TransactionKind.PAYMENT, TransactionKind.SEPA} else self.status
        return replace(
            self,
            invoice_id=invoice.invoice_id,
            invoice_number=invoice.invoice_number,
            order_number=invoice.reference or self.order_number,
            customer=invoice.customer or self.customer,
            status=status,
            reason="Manuell zugeordnet",
            selected=status == MatchStatus.READY,
        )


@dataclass(frozen=True)
class ClearingAnalysis:
    started_at: datetime
    start_date: datetime
    end_date: datetime
    candidates: tuple[ClearingCandidate, ...]
    warnings: tuple[str, ...] = ()
    run_id: str = ""

    @property
    def ready_count(self) -> int:
        return sum(row.status == MatchStatus.READY for row in self.candidates)

    @property
    def open_count(self) -> int:
        return sum(row.status in {MatchStatus.MANUAL, MatchStatus.ERROR} for row in self.candidates)


@dataclass(frozen=True)
class BookingItemResult:
    candidate_id: str
    success: bool
    status: MatchStatus
    message: str
    transaction_id: int | None = None


@dataclass(frozen=True)
class BookingBatchResult:
    items: tuple[BookingItemResult, ...] = field(default_factory=tuple)

    @property
    def success_count(self) -> int:
        return sum(item.success for item in self.items)

    @property
    def failure_count(self) -> int:
        return len(self.items) - self.success_count


@dataclass(frozen=True)
class ResetItemResult:
    transaction_id: int
    account_id: int
    success: bool
    before_status: int
    after_status: int
    message: str


@dataclass(frozen=True)
class ResetBatchResult:
    items: tuple[ResetItemResult, ...] = field(default_factory=tuple)

    @property
    def success_count(self) -> int:
        return sum(item.success for item in self.items)

    @property
    def failure_count(self) -> int:
        return len(self.items) - self.success_count
