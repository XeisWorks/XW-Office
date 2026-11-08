"""Generic read/poll adapter for final sevDesk invoices outside XW-Office."""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime
from typing import Protocol

from xw_office.services.product_hub.invoice_inventory import InvoiceInventoryBookingService, InvoiceInventoryLine


class InvoiceReleaseProvider(Protocol):
    def list_final_invoices(self, *, since: datetime.date | None = None) -> list[dict]: ...
    def list_invoice_positions(self, invoice_id: str) -> list[dict]: ...


@dataclass
class InvoicePollResult:
    processed: int = 0
    already_applied: int = 0
    needs_review: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SevdeskInvoiceInventoryPoller:
    """Book only final, exact SKU/position invoice lines; never drafts."""

    def __init__(self, provider: InvoiceReleaseProvider, booking: InvoiceInventoryBookingService) -> None:
        self._provider = provider
        self._booking = booking

    def poll(self, *, since: datetime.date | None = None) -> InvoicePollResult:
        result = InvoicePollResult()
        for invoice in self._provider.list_final_invoices(since=since):
            if _is_draft(invoice):
                continue
            invoice_id = str(invoice.get("id") or "").strip()
            if not invoice_id:
                result.needs_review.append("Rechnung ohne ID")
                continue
            revision = str(invoice.get("updated") or invoice.get("version") or "").strip()
            for position in self._provider.list_invoice_positions(invoice_id):
                if str(position.get("kind") or "product").strip().casefold() not in {"product", ""}:
                    continue
                quantity = _quantity(position)
                if quantity <= 0:
                    continue
                sku = _sku(position)
                position_key = _position_key(position)
                if not sku or not position_key:
                    result.needs_review.append(f"{invoice_id}: Position ohne SKU/ID")
                    continue
                resolved = self._booking.resolve_physical_sku(sku)
                if resolved is None:
                    result.needs_review.append(f"{invoice_id}: SKU {sku} nicht eindeutig physisch auflösbar")
                    continue
                try:
                    applied = self._booking.apply_line(
                        InvoiceInventoryLine(
                            document_id=invoice_id,
                            position_key=position_key,
                            variant_id=resolved.variant.id,
                            quantity=quantity,
                            source_revision=revision,
                        ),
                        source="sevdesk.final_invoice_poll",
                    )
                except ValueError as exc:
                    result.errors.append(f"{invoice_id}: {exc}")
                    continue
                if applied.status == "already_applied":
                    result.already_applied += 1
                else:
                    result.processed += 1
        return result


def _is_draft(document: dict) -> bool:
    try:
        return int(document.get("status")) == 100
    except (TypeError, ValueError):
        return str(document.get("status") or "").strip().casefold() in {"draft", "entwurf"}


def _quantity(position: dict) -> int:
    try:
        return max(0, int(float(position.get("quantity", position.get("qty", 0)))))
    except (TypeError, ValueError):
        return 0


def _sku(position: dict) -> str:
    part = position.get("part") if isinstance(position.get("part"), dict) else {}
    return str(position.get("sku") or position.get("partNumber") or part.get("number") or "").strip().upper()


def _position_key(position: dict) -> str:
    for key in ("id", "positionNumber", "position"):
        if str(position.get(key) or "").strip():
            return str(position[key]).strip()
    return ""


__all__ = ["InvoicePollResult", "InvoiceReleaseProvider", "SevdeskInvoiceInventoryPoller"]
