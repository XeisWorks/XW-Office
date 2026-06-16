"""Payment clearing between Stripe/Mollie/Wix and sevDesk."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from xw_studio.repositories.settings_kv import SettingKvRepository
from xw_studio.services.clearing.gateways import (
    MollieClearingGateway,
    SevdeskClearingGateway,
    StripeClearingGateway,
    WixClearingGateway,
    purpose_provider_ref,
    transaction_duplicate_key,
)
from xw_studio.services.clearing.models import (
    BookingBatchResult,
    BookingItemResult,
    ClearingAnalysis,
    ClearingCandidate,
    ClearingDuplicateKey,
    InvoiceRecord,
    MatchStatus,
    ProviderTransaction,
    SevdeskTransaction,
    TransactionKind,
)

logger = logging.getLogger(__name__)
VIENNA = ZoneInfo("Europe/Vienna")
_QUEUE_MOLLIE_KEY = "daily_business.queue.mollie"
_ORDER_NUMBER = re.compile(r"(?<!\d)(\d{5})(?!\d)")


def default_clearing_history_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "state" / "clearing_runs"


@dataclass(frozen=True)
class ClearingRow:
    """Compatibility row for the former daily-business queue."""

    ref: str
    customer: str
    amount: str
    status: str
    note: str


def _order_number(value: object) -> str:
    text = str(value or "").strip()
    if text.isdigit() and 3 <= len(text) <= 10:
        return text
    matches = _ORDER_NUMBER.findall(text)
    return matches[-1] if matches else ""


def _candidate_id(tx: ProviderTransaction) -> str:
    return hashlib.sha256(tx.stable_key.encode("utf-8")).hexdigest()[:20]


def _run_id(value: datetime) -> str:
    return value.isoformat().replace(":", "-").replace(".", "-")


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (MatchStatus, TransactionKind)):
        return value.value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _candidate_to_dict(row: ClearingCandidate) -> dict[str, object]:
    return {
        "candidate_id": row.candidate_id,
        "provider": row.provider,
        "kind": row.kind.value,
        "provider_ref": row.provider_ref,
        "order_number": row.order_number,
        "invoice_id": row.invoice_id,
        "invoice_number": row.invoice_number,
        "customer": row.customer,
        "amount": f"{row.amount:.2f}",
        "payment_date": row.payment_date.isoformat(),
        "status": row.status.value,
        "reason": row.reason,
        "selected": row.selected,
        "account_id": row.account_id,
        "transaction_id": row.transaction_id,
        "stable_key": row.stable_key,
    }


def _booking_item_to_dict(item: BookingItemResult) -> dict[str, object]:
    return {
        "candidate_id": item.candidate_id,
        "success": item.success,
        "status": item.status.value,
        "message": item.message,
        "transaction_id": item.transaction_id,
    }


def _provider_for_duplicate(row: ProviderTransaction | ClearingCandidate) -> str:
    return "payout" if row.kind == TransactionKind.PAYOUT else row.provider


def _duplicate_key_for_provider(tx: ProviderTransaction) -> ClearingDuplicateKey:
    return ClearingDuplicateKey(
        kind=tx.kind,
        provider=_provider_for_duplicate(tx),
        provider_ref=tx.provider_ref,
        value_date=tx.created_at.date().isoformat(),
        amount=tx.amount,
    )


def _duplicate_key_for_candidate(row: ClearingCandidate) -> ClearingDuplicateKey:
    return ClearingDuplicateKey(
        kind=row.kind,
        provider=_provider_for_duplicate(row),
        provider_ref=row.provider_ref,
        value_date=row.payment_date.date().isoformat(),
        amount=row.amount,
    )


class PaymentClearingService:
    """Read-only analysis and explicitly confirmed, idempotent batch booking."""

    def __init__(
        self,
        settings_repo: SettingKvRepository | None = None,
        *,
        stripe: StripeClearingGateway | None = None,
        mollie: MollieClearingGateway | None = None,
        wix: WixClearingGateway | None = None,
        sevdesk: SevdeskClearingGateway | None = None,
        history_dir: Path | None = None,
    ) -> None:
        self._repo = settings_repo
        self._stripe = stripe
        self._mollie = mollie
        self._wix = wix
        self._sevdesk = sevdesk
        self._history_dir = history_dir or default_clearing_history_dir()

    def describe(self) -> str:
        return (
            "Stripe, Mollie und SEPA automatisch mit Wix-Bestellungen und "
            "sevDesk-Rechnungen abgleichen und gesammelt buchen."
        )

    def is_configured(self) -> bool:
        return self._sevdesk is not None and self._wix is not None and (
            self._stripe is not None or self._mollie is not None
        )

    def analyze(
        self,
        start_date: date,
        end_date: date,
        *,
        progress: Callable[[int, str], None] | None = None,
    ) -> ClearingAnalysis:
        """Build a read-only clearing result. No external write is performed."""
        if self._sevdesk is None:
            raise RuntimeError("sevDesk-Clearing ist nicht konfiguriert.")
        start = datetime.combine(start_date, time.min, tzinfo=VIENNA)
        end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=VIENNA)
        if start >= end:
            raise ValueError("Der Start muss vor dem Ende liegen.")

        warnings: list[str] = []
        started_at = datetime.now(VIENNA)
        run_id = _run_id(started_at)
        provider_rows: list[ProviderTransaction] = []
        providers = (("Stripe", self._stripe), ("Mollie", self._mollie))
        for index, (label, gateway) in enumerate(providers, start=1):
            if progress:
                progress(index * 10, f"{label}-Daten laden")
            if gateway is None or not gateway.available():
                warnings.append(f"{label} ist nicht konfiguriert.")
                continue
            try:
                provider_rows.extend(gateway.fetch(start, end))
            except Exception as exc:
                logger.exception("%s clearing read failed", label)
                warnings.append(f"{label}-Daten konnten nicht geladen werden: {exc}")

        if progress:
            progress(35, "Wix-Bestellungen und Zahlungsreferenzen laden")
        provider_map: dict[str, str] = {}
        if self._wix is not None and self._wix.available():
            try:
                provider_map, _ = self._wix.provider_map(start - timedelta(days=10), end)
            except Exception as exc:
                logger.exception("Wix clearing read failed")
                warnings.append(f"Wix-Daten konnten nicht geladen werden: {exc}")
        else:
            warnings.append("Wix ist nicht konfiguriert.")

        if progress:
            progress(50, "sevDesk-Konten und Rechnungen laden")
        accounts = self._sevdesk.account_ids()
        missing_accounts = [name.title() for name in ("stripe", "mollie") if name not in accounts]
        if missing_accounts:
            warnings.append("sevDesk-Onlinekonto fehlt: " + ", ".join(missing_accounts))
        invoices = self._sevdesk.invoices(start - timedelta(days=45), end + timedelta(days=5))
        invoice_by_ref, duplicate_refs = self._invoice_index(invoices)

        if progress:
            progress(65, "Vorhandene sevDesk-Transaktionen pruefen")
        existing_by_duplicate: dict[tuple[str, str, str, str, Decimal], SevdeskTransaction] = {}
        all_existing: list[SevdeskTransaction] = []
        for account_id in accounts.values():
            rows = self._sevdesk.transactions(account_id, start - timedelta(days=45), end + timedelta(days=5))
            all_existing.extend(rows)
            for row in rows:
                key = transaction_duplicate_key(row)
                if key.provider_ref:
                    existing_by_duplicate[key.as_tuple()] = row

        candidates: list[ClearingCandidate] = []
        seen_invoice_ids: set[int] = set()
        for tx in provider_rows:
            raw_order = tx.order_number.strip()
            order_no = provider_map.get(raw_order, "")
            if not order_no and raw_order and self._wix is not None and "-" in raw_order:
                try:
                    order_no = self._wix.resolve_order_number(raw_order)
                except Exception as exc:
                    logger.warning("Wix direct order resolve failed for %s: %s", raw_order, exc)
            if not order_no and "-" not in raw_order:
                order_no = _order_number(raw_order)
            if not order_no:
                for ref in (tx.provider_ref, tx.provider_order_id, tx.source_id):
                    if ref and ref in provider_map:
                        order_no = provider_map[ref]
                        break
            invoice = invoice_by_ref.get(order_no)
            existing = existing_by_duplicate.get(_duplicate_key_for_provider(tx).as_tuple())
            candidate = self._match_provider_transaction(
                tx,
                order_no=order_no,
                invoice=invoice,
                duplicate_refs=duplicate_refs,
                existing=existing,
                account_id=accounts.get(tx.provider),
                invoice_already_used=bool(invoice and invoice.invoice_id in seen_invoice_ids),
            )
            if candidate.status == MatchStatus.READY and candidate.invoice_id is not None:
                seen_invoice_ids.add(candidate.invoice_id)
            candidates.append(candidate)

        if progress:
            progress(80, "SEPA-Zahlungen abgleichen")
        provider_refs = {tx.provider_ref for tx in provider_rows}
        for sepa_tx in all_existing:
            if (
                sepa_tx.status == 400
                or sepa_tx.amount <= Decimal("0")
                or purpose_provider_ref(sepa_tx.purpose) in provider_refs
            ):
                continue
            order_no = _order_number(sepa_tx.purpose)
            if not order_no:
                continue
            invoice = invoice_by_ref.get(order_no)
            if invoice is None or invoice.invoice_id in seen_invoice_ids:
                continue
            status, reason = self._invoice_match_status(
                invoice,
                sepa_tx.amount,
                duplicate_refs,
                order_no,
            )
            selected = status == MatchStatus.READY
            candidates.append(
                ClearingCandidate(
                    candidate_id=f"sepa-{sepa_tx.transaction_id}",
                    provider="sepa",
                    kind=TransactionKind.SEPA,
                    provider_ref=str(sepa_tx.transaction_id),
                    order_number=order_no,
                    invoice_id=invoice.invoice_id,
                    invoice_number=invoice.invoice_number,
                    customer=invoice.customer,
                    amount=sepa_tx.amount,
                    payment_date=sepa_tx.value_date,
                    status=status,
                    reason=reason,
                    selected=selected,
                    account_id=sepa_tx.account_id,
                    transaction_id=sepa_tx.transaction_id,
                    stable_key=f"sepa|{sepa_tx.transaction_id}",
                )
            )
            if selected:
                seen_invoice_ids.add(invoice.invoice_id)

        candidates.sort(key=lambda row: (row.payment_date, row.provider, row.provider_ref))
        if progress:
            progress(100, "Analyse abgeschlossen")
        analysis = ClearingAnalysis(
            started_at=started_at,
            start_date=start,
            end_date=end,
            candidates=tuple(candidates),
            warnings=tuple(warnings),
            run_id=run_id,
        )
        self._write_analysis_history(analysis)
        return analysis

    @staticmethod
    def _invoice_index(
        invoices: list[InvoiceRecord],
    ) -> tuple[dict[str, InvoiceRecord], set[str]]:
        by_ref: dict[str, InvoiceRecord] = {}
        duplicates: set[str] = set()
        for invoice in invoices:
            ref = _order_number(invoice.reference)
            if not ref:
                continue
            if ref in by_ref:
                duplicates.add(ref)
            else:
                by_ref[ref] = invoice
        return by_ref, duplicates

    @staticmethod
    def _invoice_match_status(
        invoice: InvoiceRecord,
        amount: Decimal,
        duplicate_refs: set[str],
        order_no: str,
    ) -> tuple[MatchStatus, str]:
        if order_no in duplicate_refs:
            return MatchStatus.MANUAL, "Mehrere sevDesk-Rechnungen mit derselben Referenz"
        if invoice.is_paid:
            return MatchStatus.ALREADY_BOOKED, "Rechnung ist bereits bezahlt"
        if invoice.is_draft:
            return MatchStatus.MANUAL, "Rechnung ist noch ein Entwurf"
        if invoice.amount != amount:
            return MatchStatus.MANUAL, f"Betrag weicht ab: Zahlung {amount:.2f}, Rechnung {invoice.amount:.2f}"
        return MatchStatus.READY, "Eindeutiger Treffer"

    def _match_provider_transaction(
        self,
        tx: ProviderTransaction,
        *,
        order_no: str,
        invoice: InvoiceRecord | None,
        duplicate_refs: set[str],
        existing: SevdeskTransaction | None,
        account_id: int | None,
        invoice_already_used: bool,
    ) -> ClearingCandidate:
        status = MatchStatus.MANUAL
        reason = "Keine passende Wix-Bestellung gefunden"
        selected = False
        if account_id is None:
            status, reason = MatchStatus.ERROR, f"sevDesk-Konto {tx.provider.title()} fehlt"
        elif tx.kind == TransactionKind.PAYOUT:
            status = MatchStatus.IMPORT_ONLY
            reason = "Wird als Auszahlung importiert"
            selected = True
        elif tx.kind == TransactionKind.REFUND:
            if not order_no:
                status, reason = MatchStatus.REFUND_REVIEW, "Refund: keine eindeutige Wix-Bestellnummer"
            elif invoice is None:
                status, reason = MatchStatus.REFUND_REVIEW, "Refund: keine sevDesk-Rechnung gefunden; Gutschrift fehlt?"
            elif invoice.is_draft:
                status, reason = MatchStatus.REFUND_REVIEW, "Refund: Rechnung ist noch Entwurf; Gutschrift/Storno pruefen"
            else:
                status = MatchStatus.REFUND_IMPORT
                reason = (
                    f"Refund: Rechnung {invoice.invoice_number} gefunden; "
                    "Transaktion kann importiert werden, Gutschrift/Storno separat pruefen"
                )
                selected = False
        elif not order_no:
            status, reason = MatchStatus.MANUAL, "Keine eindeutige Wix-Bestellnummer"
        elif invoice is None:
            status, reason = MatchStatus.MANUAL, "Keine sevDesk-Rechnung zur Wix-Bestellnummer"
        elif invoice_already_used:
            status, reason = MatchStatus.MANUAL, "Rechnung wurde bereits einer anderen Zahlung zugeordnet"
        else:
            status, reason = self._invoice_match_status(invoice, tx.amount, duplicate_refs, order_no)
            selected = status == MatchStatus.READY

        transaction_id = existing.transaction_id if existing else None
        if transaction_id and existing is not None and existing.status == 400:
            status, reason, selected = MatchStatus.ALREADY_BOOKED, "Transaktion ist bereits gebucht", False

        return ClearingCandidate(
            candidate_id=_candidate_id(tx),
            provider=tx.provider,
            kind=tx.kind,
            provider_ref=tx.provider_ref,
            order_number=order_no,
            invoice_id=invoice.invoice_id if invoice else None,
            invoice_number=invoice.invoice_number if invoice else "",
            customer=(invoice.customer if invoice else "") or tx.customer,
            amount=tx.amount,
            payment_date=tx.created_at,
            status=status,
            reason=reason,
            selected=selected,
            account_id=account_id,
            transaction_id=transaction_id,
            stable_key=tx.stable_key,
        )

    def assign_invoice(
        self,
        candidate: ClearingCandidate,
        invoice_number: str,
    ) -> ClearingCandidate:
        if self._sevdesk is None:
            raise RuntimeError("sevDesk-Clearing ist nicht konfiguriert.")
        invoice = self._sevdesk.find_invoice(invoice_number.strip())
        if invoice is None:
            raise ValueError(f"Rechnung {invoice_number} wurde nicht gefunden.")
        if invoice.is_paid:
            raise ValueError(f"Rechnung {invoice.invoice_number} ist bereits bezahlt.")
        if invoice.amount != candidate.amount:
            raise ValueError(
                f"Betrag passt nicht: Zahlung {candidate.amount:.2f}, Rechnung {invoice.amount:.2f}."
            )
        return candidate.with_manual_invoice(invoice)

    def book_selected(
        self,
        candidates: list[ClearingCandidate],
        *,
        progress: Callable[[int, str], None] | None = None,
    ) -> BookingBatchResult:
        """Write selected rows after UI confirmation, rechecking idempotency per row."""
        if self._sevdesk is None:
            raise RuntimeError("sevDesk-Clearing ist nicht konfiguriert.")
        selected = [row for row in candidates if row.selected and row.is_bookable]
        results: list[BookingItemResult] = []
        total = len(selected)
        for index, row in enumerate(selected, start=1):
            if progress:
                progress(int((index - 1) / max(total, 1) * 100), f"{row.provider_ref} buchen")
            try:
                transaction_id = row.transaction_id
                if row.account_id is not None and row.kind != TransactionKind.SEPA:
                    existing = self._sevdesk.find_transaction_by_duplicate_key(
                        row.account_id,
                        _duplicate_key_for_candidate(row),
                        row.payment_date,
                    )
                    if existing is not None:
                        transaction_id = existing.transaction_id
                        if existing.status == 400:
                            results.append(
                                BookingItemResult(
                                    row.candidate_id,
                                    True,
                                    MatchStatus.ALREADY_BOOKED,
                                    "Transaktion war bereits gebucht",
                                    transaction_id,
                                )
                            )
                            continue
                if transaction_id is None:
                    if row.account_id is None:
                        raise RuntimeError("Kein sevDesk-Konto zugeordnet")
                    transaction_id = self._sevdesk.create_transaction(
                        account_id=row.account_id,
                        amount=row.amount,
                        value_date=row.payment_date,
                        payee=row.customer or row.provider.title(),
                        purpose=self._candidate_purpose(row),
                    )
                if row.kind in {TransactionKind.PAYMENT, TransactionKind.SEPA}:
                    if row.invoice_id is None or row.account_id is None:
                        raise RuntimeError("Keine eindeutige Rechnung zugeordnet")
                    current_invoice = self._sevdesk.find_invoice(row.invoice_number)
                    if current_invoice is None:
                        raise RuntimeError(f"Rechnung {row.invoice_number} wurde nicht mehr gefunden")
                    if current_invoice.is_paid:
                        results.append(
                            BookingItemResult(
                                row.candidate_id,
                                True,
                                MatchStatus.ALREADY_BOOKED,
                                f"Rechnung {row.invoice_number} war bereits bezahlt",
                                transaction_id,
                            )
                        )
                        continue
                    if current_invoice.amount != row.amount:
                        raise RuntimeError(
                            f"Betrag hat sich geaendert: Zahlung {row.amount:.2f}, "
                            f"Rechnung {current_invoice.amount:.2f}"
                        )
                    self._sevdesk.book_invoice(
                        invoice_id=current_invoice.invoice_id,
                        amount=row.amount,
                        payment_date=row.payment_date,
                        account_id=row.account_id,
                        transaction_id=transaction_id,
                    )
                    status = MatchStatus.BOOKED
                    message = f"Rechnung {row.invoice_number} gebucht"
                else:
                    status = MatchStatus.BOOKED
                    message = f"{row.kind.value} in sevDesk importiert"
                results.append(
                    BookingItemResult(row.candidate_id, True, status, message, transaction_id)
                )
            except Exception as exc:
                logger.exception("Clearing row %s failed", row.candidate_id)
                results.append(
                    BookingItemResult(row.candidate_id, False, MatchStatus.ERROR, str(exc), row.transaction_id)
                )
        if progress:
            progress(100, "Buchung abgeschlossen")
        result = BookingBatchResult(tuple(results))
        self._write_booking_history(candidates, result)
        return result

    @staticmethod
    def _candidate_purpose(row: ClearingCandidate) -> str:
        kind = "PAYOUT" if row.kind == TransactionKind.PAYOUT else (
            "REFUND" if row.kind == TransactionKind.REFUND else "PAYMENT"
        )
        prefix = f"payout:{row.provider_ref}" if kind == "PAYOUT" else f"{row.provider}:{row.provider_ref}"
        order = f"order:{row.order_number}" if row.order_number else "UNMATCHED"
        return f"{order} | {prefix} | {kind}"

    def _write_analysis_history(self, analysis: ClearingAnalysis) -> None:
        payload: dict[str, object] = {
            "run_id": analysis.run_id,
            "phase": "analysis",
            "created_at": datetime.now(VIENNA).isoformat(),
            "range": {
                "start_date": analysis.start_date.date().isoformat(),
                "end_date": (analysis.end_date - timedelta(days=1)).date().isoformat(),
            },
            "summary": {
                "total": len(analysis.candidates),
                "ready": analysis.ready_count,
                "open": analysis.open_count,
                "warnings": len(analysis.warnings),
            },
            "warnings": list(analysis.warnings),
            "candidates": [_candidate_to_dict(row) for row in analysis.candidates],
        }
        self._write_history_file(f"clearing_analysis_{analysis.run_id}.json", payload)

    def _write_booking_history(
        self,
        candidates: list[ClearingCandidate],
        result: BookingBatchResult,
    ) -> None:
        started = min((row.payment_date for row in candidates), default=datetime.now(VIENNA))
        payload: dict[str, object] = {
            "run_id": _run_id(datetime.now(VIENNA)),
            "phase": "booking",
            "created_at": datetime.now(VIENNA).isoformat(),
            "summary": {
                "selected": len([row for row in candidates if row.selected and row.is_bookable]),
                "successful": result.success_count,
                "failed": result.failure_count,
            },
            "range_hint": {
                "first_payment_date": started.date().isoformat(),
            },
            "items": [_booking_item_to_dict(item) for item in result.items],
        }
        self._write_history_file(f"clearing_booking_{payload['run_id']}.json", payload)

    def _write_history_file(self, filename: str, payload: dict[str, object]) -> None:
        try:
            self._history_dir.mkdir(parents=True, exist_ok=True)
            path = self._history_dir / filename
            path.write_text(json.dumps(_json_value(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Clearing history could not be written: %s", exc)

    # Compatibility helpers retained for the existing daily-business queue.
    def list_pending(self) -> list[ClearingRow]:
        if self._repo is None:
            return []
        raw = self._repo.get_value_json(_QUEUE_MOLLIE_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid clearing JSON in %s", _QUEUE_MOLLIE_KEY)
            return []
        if not isinstance(data, list):
            return []
        return [
            ClearingRow(
                ref=str(item.get("ref") or ""),
                customer=str(item.get("customer") or ""),
                amount=str(item.get("amount") or ""),
                status=str(item.get("status") or ""),
                note=str(item.get("note") or ""),
            )
            for item in data
            if isinstance(item, dict)
        ]

    def filter_rows(
        self,
        rows: list[ClearingRow],
        needle: str = "",
        status: str = "",
    ) -> list[ClearingRow]:
        search = needle.casefold().strip()
        want_status = status.casefold().strip()
        return [
            row
            for row in rows
            if (not want_status or row.status.casefold().strip() == want_status)
            and (
                not search
                or search
                in f"{row.ref} {row.customer} {row.amount} {row.status} {row.note}".casefold()
            )
        ]

    def export_csv(self, rows: list[ClearingRow]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(["Ref", "Kunde", "Betrag", "Status", "Hinweis"])
        for row in rows:
            writer.writerow([row.ref, row.customer, row.amount, row.status, row.note])
        return buf.getvalue()
