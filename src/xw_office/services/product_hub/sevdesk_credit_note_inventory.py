"""Conservative sevDesk credit-note feed adapter for inventory reversals."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from xw_office.services.product_hub.invoice_inventory import InvoiceInventoryBookingService, InvoiceInventoryLine
from xw_office.services.product_hub.sevdesk_feed_validation import document_state, feed_quantity


class CreditNoteProvider(Protocol):
    def list_credit_notes_for_year(self, year: int) -> list[dict[str, object]]: ...
    def list_credit_note_positions(self, credit_note_id: str) -> list[dict[str, object]]: ...


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
        credits = self._provider.list_credit_notes_for_year(year)
        bulk_positions = _bulk_positions(
            self._provider, credits, "list_credit_note_positions_bulk", "creditNote"
        )
        for credit in credits:
            state = document_state(credit)
            if state == "draft":
                continue
            credit_id = str(credit.get("id") or "").strip()
            if not credit_id:
                result.needs_review.append("Gutschrift ohne ID")
                continue
            if state != "final":
                result.needs_review.append(f"{credit_id}: unbekannter oder nicht finaler Status")
                continue
            origin_invoice = _origin_invoice_id(credit)
            if not origin_invoice:
                result.needs_review.append(f"{credit_id}: Ursprungsrechnung nicht eindeutig")
                continue
            positions = (
                bulk_positions.get(credit_id, [])
                if bulk_positions is not None
                else self._provider.list_credit_note_positions(credit_id)
            )
            for position in positions:
                quantity = feed_quantity(position)
                if quantity is None or quantity != quantity.to_integral_value():
                    result.needs_review.append(f"{credit_id}: ungültige/bruchteilige Positionsmenge")
                    continue
                if quantity == 0:
                    continue
                quantity_int = int(quantity)
                origin_position = _origin_position_key(position)
                sku = _sku(position)
                position_key = _position_key(position)
                if not origin_position or not sku or not position_key:
                    result.needs_review.append(
                        f"{credit_id}: Position ohne Positions-ID/Ursprungsposition/SKU"
                    )
                    continue
                resolved = self._booking.resolve_physical_sku(sku)  # exact Hub resolution; no guessing
                if resolved is None:
                    result.needs_review.append(f"{credit_id}: SKU {sku} nicht eindeutig physisch auflösbar")
                    continue
                try:
                    applied = self._booking.apply_credit_line(
                        InvoiceInventoryLine(
                            document_id=credit_id,
                            position_key=position_key,
                            variant_id=resolved.variant.id,
                            quantity=quantity_int,
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
                        position_key=position_key,
                        variant_id=resolved.variant.id,
                        quantity=quantity_int,
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


def _origin_invoice_id(document: dict[str, object]) -> str:
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


def _origin_position_key(position: dict[str, object]) -> str:
    for key in ("invoicePosId", "invoicePositionId", "originPositionId", "refInvoicePosId", "originalPositionKey"):
        value = position.get(key)
        if isinstance(value, dict):
            value = value.get("id")
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _position_key(position: dict[str, object]) -> str:
    return str(position.get("id") or position.get("creditNotePosId") or "").strip()


def _sku(position: dict[str, object]) -> str:
    raw_part = position.get("part")
    part = raw_part if isinstance(raw_part, dict) else {}
    return str(position.get("sku") or position.get("partNumber") or part.get("number") or "").strip().upper()


def _bulk_positions(
    provider: object,
    documents: list[dict[str, object]],
    method_name: str,
    parent_key: str,
) -> dict[str, list[dict[str, object]]] | None:
    loader = getattr(provider, method_name, None)
    if not callable(loader):
        return None
    ids = [str(document.get("id") or "").strip() for document in documents]
    grouped: dict[str, list[dict[str, object]]] = {}
    for position in loader(ids):
        if not isinstance(position, dict):
            continue
        parent = position.get(parent_key)
        parent_id = str(parent.get("id") if isinstance(parent, dict) else parent or "").strip()
        if parent_id:
            grouped.setdefault(parent_id, []).append(dict(position))
    return grouped


__all__ = ["CreditNoteProcessingResult", "CreditNoteProvider", "SevdeskCreditNoteInventoryService"]
