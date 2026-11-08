"""Conservative sevDesk credit-note feed adapter for inventory reversals."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from xw_office.services.product_hub.invoice_inventory import InvoiceInventoryBookingService, InvoiceInventoryLine


class CreditNoteProvider(Protocol):
    def list_credit_notes_for_year(self, year: int) -> list[dict]: ...
    def list_credit_note_positions(self, credit_note_id: str) -> list[dict]: ...


@dataclass
class CreditNoteProcessingResult:
    processed: int = 0
    already_applied: int = 0
    needs_review: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SevdeskCreditNoteInventoryService:
    """Apply only credit positions with explicit origin invoice and position IDs."""

    def __init__(
        self,
        provider: CreditNoteProvider,
        booking: InvoiceInventoryBookingService,
        on_applied: Callable[[InvoiceInventoryLine, object], object] | None = None,
    ) -> None:
        self._provider = provider
        self._booking = booking
        self._on_applied = on_applied

    def process_year(self, year: int) -> CreditNoteProcessingResult:
        result = CreditNoteProcessingResult()
        for credit in self._provider.list_credit_notes_for_year(year):
            if _is_draft(credit):
                continue
            credit_id = str(credit.get("id") or "").strip()
            if not credit_id:
                result.needs_review.append("Gutschrift ohne ID")
                continue
            origin_invoice = _origin_invoice_id(credit)
            if not origin_invoice:
                result.needs_review.append(f"{credit_id}: Ursprungsrechnung nicht eindeutig")
                continue
            for position in self._provider.list_credit_note_positions(credit_id):
                quantity = _quantity(position)
                if quantity <= 0:
                    continue
                origin_position = _origin_position_key(position)
                sku = _sku(position)
                if not origin_position or not sku:
                    result.needs_review.append(f"{credit_id}: Position ohne Ursprungsposition/SKU")
                    continue
                resolved = self._booking.resolve_physical_sku(sku)  # exact Hub resolution; no guessing
                if resolved is None:
                    result.needs_review.append(f"{credit_id}: SKU {sku} nicht eindeutig physisch auflösbar")
                    continue
                try:
                    applied = self._booking.apply_credit_line(
                        InvoiceInventoryLine(
                            document_id=credit_id,
                            position_key=_position_key(position),
                            variant_id=resolved.variant.id,
                            quantity=quantity,
                            movement_kind="return",
                            original_document_id=origin_invoice,
                            original_position_key=origin_position,
                        )
                    )
                except ValueError as exc:
                    result.errors.append(f"{credit_id}: {exc}")
                    continue
                if applied.status == "already_applied":
                    result.already_applied += 1
                else:
                    result.processed += 1
                if self._on_applied is not None:
                    mirror_line = InvoiceInventoryLine(
                        document_id=credit_id,
                        position_key=_position_key(position),
                        variant_id=resolved.variant.id,
                        quantity=quantity,
                        movement_kind="return",
                        original_document_id=origin_invoice,
                        original_position_key=origin_position,
                    )
                    mirror = self._on_applied(mirror_line, applied)
                    mirror_status = str(getattr(mirror, "status", ""))
                    if mirror_status not in {"mirrored", "already_applied"}:
                        result.needs_review.append(
                            f"{credit_id}/{_position_key(position)}: Legacy-Mirror {mirror_status or 'unbekannt'} "
                            f"{getattr(mirror, 'detail', '')}".strip()
                        )
        return result


def _is_draft(document: dict) -> bool:
    try:
        return int(document.get("status")) == 100
    except (TypeError, ValueError):
        return str(document.get("status") or "").strip().casefold() in {"draft", "entwurf"}


def _origin_invoice_id(document: dict) -> str:
    for key in ("invoiceId", "invoice_id", "refInvoiceId", "originInvoiceId"):
        value = document.get(key)
        if isinstance(value, dict):
            value = value.get("id")
        if str(value or "").strip():
            return str(value).strip()
    for key in ("invoice", "refInvoice", "originInvoice"):
        value = document.get(key)
        if isinstance(value, dict) and str(value.get("id") or "").strip():
            return str(value["id"]).strip()
    return ""


def _origin_position_key(position: dict) -> str:
    for key in ("invoicePosId", "invoicePositionId", "originPositionId", "refInvoicePosId", "originalPositionKey"):
        value = position.get(key)
        if isinstance(value, dict):
            value = value.get("id")
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _position_key(position: dict) -> str:
    for key in ("id", "positionNumber", "position", "creditNotePosId"):
        if str(position.get(key) or "").strip():
            return str(position[key]).strip()
    return "position-unknown"


def _sku(position: dict) -> str:
    part = position.get("part") if isinstance(position.get("part"), dict) else {}
    return str(position.get("sku") or position.get("partNumber") or part.get("number") or "").strip().upper()


def _quantity(position: dict) -> int:
    try:
        return max(0, int(float(position.get("quantity", position.get("qty", 0)))))
    except (TypeError, ValueError):
        return 0


__all__ = ["CreditNoteProcessingResult", "CreditNoteProvider", "SevdeskCreditNoteInventoryService"]
