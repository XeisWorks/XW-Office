"""Atomic cross-PC reservations and checkpoints for clearing writes."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.clearing.models import ClearingCandidate, TransactionKind

_LEDGER_KEY = "clearing.booking_ledger.v1"


class BookingReservation(BaseModel):
    owner: str
    fingerprint: str
    state: str = "reserved"
    transaction_id: int | None = None
    invoice_id: int | None = None
    updated_at: str
    message: str = ""


class BookingLedger(BaseModel):
    entries: dict[str, BookingReservation] = Field(default_factory=dict)
    invoices: dict[str, str] = Field(default_factory=dict)


def booking_identity(row: ClearingCandidate) -> str:
    return f"{row.kind.value}|{row.provider}|{row.provider_ref}"


def _fingerprint(row: ClearingCandidate) -> str:
    text = (
        f"{row.account_id}|{row.amount:.2f}|{row.payment_date.date().isoformat()}|"
        f"{row.invoice_id if row.kind in {TransactionKind.PAYMENT, TransactionKind.SEPA} else ''}"
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ClearingBookingStore:
    def __init__(self, repo: SettingKvRepository) -> None:
        self._repo = repo

    def claim(self, row: ClearingCandidate) -> BookingReservation:
        identity = booking_identity(row)
        owner = uuid4().hex
        fingerprint = _fingerprint(row)
        invoice_id = row.invoice_id if row.kind in {TransactionKind.PAYMENT, TransactionKind.SEPA} else None

        def mutate(raw: str | None) -> str:
            ledger = BookingLedger.model_validate_json(raw) if raw else BookingLedger()
            existing = ledger.entries.get(identity)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise RuntimeError("Zahlungs-ID wurde bereits mit anderen Buchungsdaten reserviert.")
                if existing.state == "completed":
                    return ledger.model_dump_json()
                raise RuntimeError(
                    "Zahlung ist auf einem anderen PC reserviert oder ihr Schreibausgang ist unklar. "
                    "Vor erneutem Buchen in sevDesk pruefen."
                )
            if invoice_id is not None:
                invoice_key = str(invoice_id)
                if invoice_key in ledger.invoices:
                    raise RuntimeError("Rechnung ist bereits fuer eine andere Zahlungsbuchung reserviert.")
                ledger.invoices[invoice_key] = identity
            ledger.entries[identity] = BookingReservation(
                owner=owner,
                fingerprint=fingerprint,
                invoice_id=invoice_id,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            return ledger.model_dump_json()

        updated = self._repo.mutate_value_json(_LEDGER_KEY, mutate)
        return BookingLedger.model_validate_json(updated).entries[identity]

    def checkpoint(
        self,
        row: ClearingCandidate,
        reservation: BookingReservation,
        *,
        state: str,
        transaction_id: int | None,
        message: str = "",
    ) -> None:
        identity = booking_identity(row)

        def mutate(raw: str | None) -> str:
            if not raw:
                raise RuntimeError("Zentrale Buchungsreservierung fehlt.")
            ledger = BookingLedger.model_validate_json(raw)
            entry = ledger.entries.get(identity)
            if entry is None or entry.owner != reservation.owner:
                raise RuntimeError("Zentrale Buchungsreservierung wurde veraendert.")
            entry.state = state
            entry.transaction_id = transaction_id
            entry.message = message
            entry.updated_at = datetime.now(timezone.utc).isoformat()
            if state in {"completed", "released"}:
                if entry.invoice_id is not None:
                    ledger.invoices.pop(str(entry.invoice_id), None)
                if state == "released":
                    del ledger.entries[identity]
            return ledger.model_dump_json()

        self._repo.mutate_value_json(_LEDGER_KEY, mutate)
