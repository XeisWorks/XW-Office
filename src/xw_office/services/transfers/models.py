from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class TransferCaseStatus(str, Enum):
    OPEN = "open"
    DONE = "done"


class TransferFieldSource(str, Enum):
    MAIL = "mail"
    THREAD = "thread"
    PDF_TEXT = "pdf_text"
    PDF_EXISTING_QR = "pdf_existing_qr"
    OPENAI = "openai"
    MANUAL = "manual"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TransferAttachment:
    id: str
    name: str
    content_type: str
    size: int | None = None


@dataclass
class TransferPaymentData:
    recipient: str = ""
    iban: str = ""
    bic: str = ""
    amount: Decimal | None = None
    currency: str = "EUR"
    remittance_text: str = ""
    invoice_number: str = ""
    due_date: str = ""
    note: str = ""
    source_by_field: dict[str, TransferFieldSource] = field(default_factory=dict)
    confidence_by_field: dict[str, float] = field(default_factory=dict)


@dataclass
class TransferCase:
    id: str
    internet_message_id: str
    conversation_id: str
    received_at: str
    sender: str
    subject: str
    snippet: str
    body: str
    thread_text: str = ""
    summary: str = ""
    attachments: list[TransferAttachment] = field(default_factory=list)
    payment: TransferPaymentData = field(default_factory=TransferPaymentData)
    status: TransferCaseStatus = TransferCaseStatus.OPEN
    outlook_flag_status: str = "notFlagged"
    outlook_completed_at: str = ""
    deferred_at: str = ""
    defer_count: int = 0
    done_at: str = ""
    done_note: str = ""
    qr_path: str = ""
