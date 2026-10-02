"""Source-aware buyer-note and START review models."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class BuyerNoteSource:
    source: str
    label: str
    text: str


@dataclass(frozen=True)
class BuyerNoteProduct:
    quantity: str = "1"
    name: str = ""
    sku: str = ""
    note: str = ""


@dataclass(frozen=True)
class BuyerNoteCase:
    invoice_id: str
    invoice_number: str
    order_reference: str
    customer_name: str
    sources: tuple[BuyerNoteSource, ...] = ()
    physical_delivery: bool | None = None
    address_lines: tuple[str, ...] = ()
    products: tuple[BuyerNoteProduct, ...] = ()

    @property
    def note_text(self) -> str:
        return "\n\n".join(source.text.strip() for source in self.sources if source.text.strip())

    @property
    def source_labels(self) -> str:
        return ", ".join(source.label for source in self.sources)

    @property
    def fingerprint(self) -> str:
        raw = "|".join(
            (
                self.invoice_id,
                self.order_reference,
                self.note_text,
                "\n".join(self.address_lines),
            )
        )
        return sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class BuyerNoteReviewSelection:
    """A confirmed action for one START note case."""

    action: str
    address_lines: tuple[str, ...] = ()
    manual_note: str = ""


BUYER_NOTE_ACK = "acknowledge"
BUYER_NOTE_DELIVERY_NOTE = "delivery_note"
BUYER_NOTE_SKIP = "skip"
BUYER_NOTE_DIGITAL_ACK = "digital_acknowledge"


def normalized_lines(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(" ".join(str(value or "").split()) for value in values if str(value or "").strip())
