"""Confirmed, cancellable clearing batches with durable write checkpoints."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from typing import Callable

from xw_office.services.clearing.booking_store import (
    BookingReservation,
    ClearingBookingStore,
    booking_identity,
)
from xw_office.services.clearing.gateways import SevdeskClearingGateway, transaction_duplicate_key
from xw_office.services.clearing.models import (
    BookingBatchResult,
    BookingItemResult,
    ClearingCandidate,
    InvoiceRecord,
    MatchStatus,
    SevdeskTransaction,
    TransactionKind,
)

logger = logging.getLogger(__name__)


def book_batch(
    candidates: list[ClearingCandidate],
    *,
    gateway: SevdeskClearingGateway,
    store: ClearingBookingStore | None,
    current_invoice: Callable[[ClearingCandidate], InvoiceRecord],
    purpose: Callable[[ClearingCandidate], str],
    progress: Callable[[int, str], None] | None,
    cancelled: Callable[[], bool] | None,
) -> BookingBatchResult:
    unique: dict[str, ClearingCandidate] = {}
    conflicts: set[str] = set()
    for row in candidates:
        if not row.selected or not row.is_bookable:
            continue
        identity = booking_identity(row)
        previous = unique.get(identity)
        if previous is not None:
            if (previous.amount, previous.payment_date, previous.account_id, previous.invoice_id) != (
                row.amount, row.payment_date, row.account_id, row.invoice_id
            ):
                conflicts.add(identity)
        else:
            unique[identity] = row
    selected = list(unique.values())
    existing_by_identity: dict[tuple[int, TransactionKind, str], list[SevdeskTransaction]] = {}
    rows_by_account: dict[int, list[ClearingCandidate]] = {}
    for row in selected:
        if row.account_id is not None and row.kind != TransactionKind.SEPA:
            rows_by_account.setdefault(row.account_id, []).append(row)
    for account_id, rows in rows_by_account.items():
        if cancelled and cancelled():
            break
        start = min(row.payment_date for row in rows) - timedelta(days=2)
        end = max(row.payment_date for row in rows) + timedelta(days=3)
        for transaction in gateway.transactions(account_id, start, end):
            key = transaction_duplicate_key(transaction)
            if key.provider_ref:
                existing_by_identity.setdefault(
                    (account_id, key.kind, key.provider_ref), []
                ).append(transaction)

    results: list[BookingItemResult] = []
    was_cancelled = False
    for index, row in enumerate(selected):
        if progress:
            progress(int(index / max(len(selected), 1) * 100), f"{row.provider_ref} buchen")
        if cancelled and cancelled():
            was_cancelled = True
            results.extend(
                BookingItemResult(
                    pending.candidate_id, False, MatchStatus.CANCELLED,
                    "Nicht ausgefuehrt: Buchung abgebrochen.", pending.transaction_id,
                )
                for pending in selected[index:]
            )
            break
        reservation: BookingReservation | None = None
        transaction_id = row.transaction_id
        write_started = False
        try:
            if booking_identity(row) in conflicts:
                raise RuntimeError("Mehrere Kandidaten mit derselben Zahlungs-ID und abweichenden Daten.")
            if row.account_id is None:
                raise RuntimeError("Kein sevDesk-Konto zugeordnet.")
            if store is not None:
                reservation = store.claim(row)
                if reservation.state == "completed":
                    results.append(BookingItemResult(
                        row.candidate_id, True, MatchStatus.ALREADY_BOOKED,
                        "Zentrale Buchungsbestaetigung bereits vorhanden.", reservation.transaction_id,
                    ))
                    continue
            existing_rows = existing_by_identity.get((row.account_id, row.kind, row.provider_ref), [])
            if len(existing_rows) > 1:
                raise RuntimeError("Mehrere sevDesk-Transaktionen mit derselben Zahlungs-ID.")
            existing = existing_rows[0] if existing_rows else None
            if row.kind != TransactionKind.SEPA and transaction_id is not None and existing is None:
                raise RuntimeError("Zugeordnete sevDesk-Transaktion fehlt im aktuellen Abgleich; neu analysieren.")
            if existing is not None:
                if existing.amount != row.amount or existing.value_date.date() != row.payment_date.date():
                    raise RuntimeError("Zahlungs-ID in sevDesk hat einen anderen Betrag oder ein anderes Datum.")
                transaction_id = existing.transaction_id
            status = MatchStatus.BOOKED
            message = f"{row.kind.value} in sevDesk importiert"
            invoice: InvoiceRecord | None = None
            if existing is not None and existing.status == 400:
                status, message = MatchStatus.ALREADY_BOOKED, "Transaktion war bereits gebucht."
            elif row.kind in {TransactionKind.PAYMENT, TransactionKind.SEPA}:
                invoice = current_invoice(row)
                if invoice.is_paid:
                    status, message = MatchStatus.ALREADY_BOOKED, f"Rechnung {row.invoice_number} war bereits bezahlt."
            if status != MatchStatus.ALREADY_BOOKED:
                if transaction_id is None:
                    write_started = True
                    transaction_id = gateway.create_transaction(
                        account_id=row.account_id, amount=row.amount, value_date=row.payment_date,
                        payee=row.customer or row.provider.title(), purpose=purpose(row),
                    )
                    existing_by_identity[(row.account_id, row.kind, row.provider_ref)] = [
                        SevdeskTransaction(
                            transaction_id, row.account_id, row.amount, row.payment_date, purpose(row), 100
                        )
                    ]
                    if store is not None and reservation is not None:
                        store.checkpoint(
                            row, reservation, state="imported", transaction_id=transaction_id
                        )
                if invoice is not None:
                    write_started = True
                    booking_response = gateway.book_invoice(
                        invoice_id=invoice.invoice_id, amount=row.amount, payment_date=row.payment_date,
                        account_id=row.account_id, transaction_id=transaction_id,
                    )
                    book_status = str(booking_response.get("status") or "").strip().lower()
                    if book_status == "invoice_already_paid":
                        raise RuntimeError(
                            "Rechnung wurde zwischenzeitlich bezahlt; die zugeordnete "
                            "Transaktion in sevDesk pruefen. Kein erneuter Import."
                        )
                    if book_status not in {"booked", "already_booked"}:
                        raise RuntimeError(f"Zahlungsbuchung nicht bestaetigt (status={book_status or '-'}).")
                    if book_status == "already_booked":
                        status = MatchStatus.ALREADY_BOOKED
                    message = f"Rechnung {row.invoice_number} gebucht"
                    warning = str(booking_response.get("warning") or "").strip()
                    if warning:
                        message += f"; Warnung: {warning}"
            if store is not None and reservation is not None:
                store.checkpoint(
                    row, reservation, state="completed", transaction_id=transaction_id, message=message
                )
            results.append(BookingItemResult(row.candidate_id, True, status, message, transaction_id))
        except Exception as exc:
            logger.exception("Clearing row %s failed", row.candidate_id)
            message = str(exc)
            if store is not None and reservation is not None:
                try:
                    store.checkpoint(
                        row, reservation, state="uncertain" if write_started else "released",
                        transaction_id=transaction_id, message=message,
                    )
                except Exception as checkpoint_error:
                    logger.exception("Clearing checkpoint failed for %s", row.candidate_id)
                    message += f"; zentrale Sicherung fehlgeschlagen: {checkpoint_error}"
            results.append(BookingItemResult(row.candidate_id, False, MatchStatus.ERROR, message, transaction_id))
    if progress:
        progress(100, "Buchung abgebrochen" if was_cancelled else "Buchung abgeschlossen")
    result_by_identity = {
        booking_identity(row): result for row, result in zip(selected, results, strict=True)
    }
    result_ids = {result.candidate_id for result in results}
    for row in candidates:
        if row.selected and row.is_bookable and row.candidate_id not in result_ids:
            result = result_by_identity.get(booking_identity(row))
            if result is not None:
                results.append(replace(result, candidate_id=row.candidate_id))
                result_ids.add(row.candidate_id)
    return BookingBatchResult(tuple(results), cancelled=was_cancelled)
