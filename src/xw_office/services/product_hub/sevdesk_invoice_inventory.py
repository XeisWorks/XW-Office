"""Generic read/poll adapter for final sevDesk invoices outside XW-Office."""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime
from typing import Callable, Protocol

from xw_office.services.product_hub.invoice_inventory import InvoiceInventoryBookingService, InvoiceInventoryLine
from xw_office.repositories.product_hub_inventory import NegativeStockError
from xw_office.services.product_hub.sevdesk_feed_validation import document_state, feed_quantity


class InvoiceReleaseProvider(Protocol):
    def list_final_invoices(self, *, since: datetime.date | None = None) -> list[dict[str, object]]: ...
    def list_invoice_positions(self, invoice_id: str) -> list[dict[str, object]]: ...


@dataclass
class InvoicePollResult:
    processed: int = 0
    already_applied: int = 0
    needs_review: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SevdeskInvoiceInventoryPoller:
    """Book only final, exact SKU/position invoice lines; never drafts."""

    def __init__(
        self,
        provider: InvoiceReleaseProvider,
        booking: InvoiceInventoryBookingService,
        on_applied: Callable[[InvoiceInventoryLine, object], object] | None = None,
        on_shortage: Callable[[InvoiceInventoryLine, Exception], object] | None = None,
    ) -> None:
        self._provider = provider
        self._booking = booking
        self._on_applied = on_applied
        self._on_shortage = on_shortage

    def poll(self, *, since: datetime.date | None = None) -> InvoicePollResult:
        result = InvoicePollResult()
        invoices = self._provider.list_final_invoices(since=since)
        bulk_positions = _bulk_positions(self._provider, invoices, "list_invoice_positions_bulk", "invoice")
        for invoice in invoices:
            state = document_state(invoice)
            if state == "draft":
                continue
            invoice_id = str(invoice.get("id") or "").strip()
            if not invoice_id:
                result.needs_review.append("Rechnung ohne ID")
                continue
            if state != "final":
                result.needs_review.append(f"{invoice_id}: unbekannter oder nicht finaler Status")
                continue
            revision = str(invoice.get("updated") or invoice.get("version") or "").strip()
            positions = (
                bulk_positions.get(invoice_id, [])
                if bulk_positions is not None
                else self._provider.list_invoice_positions(invoice_id)
            )
            for position in positions:
                if str(position.get("kind") or "product").strip().casefold() not in {"product", ""}:
                    continue
                quantity = feed_quantity(position)
                if quantity is None or quantity != quantity.to_integral_value():
                    result.needs_review.append(f"{invoice_id}: ungültige/bruchteilige Positionsmenge")
                    continue
                if quantity == 0:
                    continue
                quantity_int = int(quantity)
                sku = _sku(position)
                position_key = _position_key(position)
                if not sku or not position_key:
                    result.needs_review.append(
                        f"{invoice_id}: Position ohne stabile Positions-ID oder SKU"
                    )
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
                            quantity=quantity_int,
                            source_revision=revision,
                        ),
                        source="sevdesk.final_invoice_poll",
                    )
                except NegativeStockError as exc:
                    if self._on_shortage is not None:
                        try:
                            self._on_shortage(
                                InvoiceInventoryLine(
                                    document_id=invoice_id,
                                    position_key=position_key,
                                    variant_id=resolved.variant.id,
                                    quantity=quantity_int,
                                    source_revision=revision,
                                ),
                                exc,
                            )
                        except Exception as callback_exc:  # noqa: BLE001
                            result.errors.append(
                                f"{invoice_id}/{position_key}: Unterdeckungs-Callback fehlgeschlagen: {callback_exc}"
                            )
                    result.needs_review.append(
                        f"{invoice_id}/{position_key}: Bestand reicht für externe Freigabe nicht aus: {exc}"
                    )
                    continue
                except ValueError as exc:
                    result.errors.append(f"{invoice_id}: {exc}")
                    continue
                if applied.status == "already_applied":
                    result.already_applied += 1
                else:
                    result.processed += 1
                if self._on_applied is not None:
                    mirror = self._on_applied(
                        InvoiceInventoryLine(
                            document_id=invoice_id,
                            position_key=position_key,
                            variant_id=resolved.variant.id,
                            quantity=quantity_int,
                            source_revision=revision,
                        ),
                        applied,
                    )
                    mirror_status = str(getattr(mirror, "status", ""))
                    if mirror_status not in {"mirrored", "already_applied"}:
                        result.needs_review.append(
                            f"{invoice_id}/{position_key}: Legacy-Mirror {mirror_status or 'unbekannt'} "
                            f"{getattr(mirror, 'detail', '')}".strip()
                        )
        return result


def _sku(position: dict[str, object]) -> str:
    raw_part = position.get("part")
    part = raw_part if isinstance(raw_part, dict) else {}
    return str(position.get("sku") or position.get("partNumber") or part.get("number") or "").strip().upper()


def _position_key(position: dict[str, object]) -> str:
    return str(position.get("id") or "").strip()


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


__all__ = ["InvoicePollResult", "InvoiceReleaseProvider", "SevdeskInvoiceInventoryPoller"]
