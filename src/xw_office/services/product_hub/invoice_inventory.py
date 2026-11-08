"""Idempotent inventory booking for finalized invoice document positions."""
from __future__ import annotations

from dataclasses import dataclass
import uuid

from sqlalchemy import func

from xw_office.core.database import session_scope
from xw_office.models.inventory_document_booking import InventoryDocumentBooking
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.services.product_hub.inventory import InventoryV2Service


@dataclass(frozen=True)
class InvoiceInventoryLine:
    document_id: str
    position_key: str
    variant_id: uuid.UUID
    quantity: int
    movement_kind: str = "sale"
    source_revision: str = ""
    original_document_id: str = ""
    original_position_key: str = ""


@dataclass(frozen=True)
class InvoiceInventoryBookingResult:
    document_id: str
    position_key: str
    previous_quantity_applied: int
    requested_quantity_applied: int
    delta: int
    movement_id: uuid.UUID | None
    status: str


class InvoiceInventoryBookingService:
    """Translate final document quantities into exactly-once ledger movements."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self._inventory = InventoryV2Service(session_factory)
        self._repository = InventoryRepository(session_factory)
        self._products = ProductHubRepository(session_factory)

    def apply_invoice_context(
        self,
        *,
        document_id: str,
        positions,
        source: str = "sevdesk.invoice_release",
    ) -> list[InvoiceInventoryBookingResult]:
        """Book resolvable physical product positions from a normalized context.

        Digital, service, shipping, discount, and unknown positions are ignored by
        design.  A product-like position without an exact Hub SKU raises so a final
        invoice cannot silently disappear from inventory accounting.
        """
        results: list[InvoiceInventoryBookingResult] = []
        unresolved: list[str] = []
        for position in positions:
            if getattr(position, "kind", "") != "product":
                continue
            sku = str(getattr(position, "sku", "") or "").strip().upper()
            quantity = getattr(position, "quantity_int", 0)
            if not sku or quantity <= 0:
                continue
            resolved = self._products.resolve_sku(sku)
            if resolved is None or not resolved.variant.active:
                unresolved.append(sku or "<ohne SKU>")
                continue
            if not resolved.variant.stock_enabled:
                continue
            results.append(
                self.apply_line(
                    InvoiceInventoryLine(
                        document_id=document_id,
                        position_key=(
                            str(getattr(position, "source_id", "") or "").strip()
                            or f"position-{getattr(position, 'position_number', 0)}"
                        ),
                        variant_id=resolved.variant.id,
                        quantity=int(quantity),
                        movement_kind="sale",
                    ),
                    source=source,
                )
            )
        if unresolved:
            raise ValueError(
                "Physische Rechnungspositionen ohne eindeutige Product-Hub-Variante: "
                + ", ".join(sorted(set(unresolved)))
            )
        return results

    def apply_credit_line(
        self,
        line: InvoiceInventoryLine,
        *,
        source: str = "sevdesk.credit_note",
    ) -> InvoiceInventoryBookingResult:
        """Apply an unambiguous credit against an existing sale booking."""
        if line.movement_kind != "return":
            raise ValueError("apply_credit_line benötigt movement_kind='return'")
        original_document_id = str(line.original_document_id or "").strip()
        original_position_key = str(line.original_position_key or "").strip()
        if not original_document_id or not original_position_key:
            raise ValueError("Gutschrift benötigt einen eindeutigen Ursprungsbeleg und Positionsschlüssel")
        sale = self._get_booking(original_document_id, original_position_key, "sale")
        if sale is None or sale.quantity_applied >= 0:
            raise ValueError("Keine gebuchte Verkaufsposition für die Gutschrift gefunden")
        existing_return = self._get_booking(line.document_id, line.position_key, "return")
        # Replaying the same credit-note position must remain idempotent.
        if existing_return is not None and existing_return.quantity_applied == line.quantity:
            return self.apply_line(line, source=source)
        already_returned = existing_return.quantity_applied if existing_return is not None else 0
        total_returned = self._get_returned_quantity(original_document_id, original_position_key)
        other_returned = max(0, total_returned - already_returned)
        max_return = max(0, -sale.quantity_applied - other_returned)
        if line.quantity > max_return:
            raise ValueError(
                f"Gutschriftmenge {line.quantity} überschreitet die noch rückbuchbare Menge {max_return}"
            )
        return self.apply_line(line, source=source)

    def apply_line(self, line: InvoiceInventoryLine, *, source: str = "sevdesk.invoice_release") -> InvoiceInventoryBookingResult:
        document_id = str(line.document_id or "").strip()
        position_key = str(line.position_key or "").strip()
        if not document_id or not position_key:
            raise ValueError("document_id und position_key sind erforderlich")
        if line.quantity < 0:
            raise ValueError("quantity darf nicht negativ sein")
        if line.movement_kind not in {"sale", "return"}:
            raise ValueError("movement_kind muss sale oder return sein")
        signed_target = -line.quantity if line.movement_kind == "sale" else line.quantity
        booking = self._get_booking(document_id, position_key, line.movement_kind)
        previous = booking.quantity_applied if booking is not None else 0
        delta = signed_target - previous
        movement_id = None
        if delta:
            key = (
                f"invoice-line:{document_id}:{position_key}:"
                f"{line.movement_kind}:target:{signed_target}"
            )
            movement = self._inventory.record_movement(
                variant_id=line.variant_id,
                delta=delta,
                reason=line.movement_kind,
                source=source,
                idempotency_key=key,
                external_reference=f"{document_id}:{position_key}",
                note="finalized document position",
            )
            movement_id = movement.movement.id
            self._upsert_booking(
                document_id=document_id,
                position_key=position_key,
                movement_kind=line.movement_kind,
                variant_id=line.variant_id,
                quantity_applied=signed_target,
                source_revision=line.source_revision,
                last_idempotency_key=key,
                original_document_id=line.original_document_id,
                original_position_key=line.original_position_key,
            )
            status = "applied"
        else:
            status = "already_applied"
        return InvoiceInventoryBookingResult(
            document_id=document_id,
            position_key=position_key,
            previous_quantity_applied=previous,
            requested_quantity_applied=signed_target,
            delta=delta,
            movement_id=movement_id,
            status=status,
        )

    def _get_booking(
        self, document_id: str, position_key: str, movement_kind: str
    ) -> InventoryDocumentBooking | None:
        with session_scope(self._session_factory) as session:
            return session.query(InventoryDocumentBooking).filter_by(
                document_id=document_id,
                position_key=position_key,
                movement_kind=movement_kind,
            ).one_or_none()

    def _upsert_booking(self, **values: object) -> InventoryDocumentBooking:
        with session_scope(self._session_factory) as session:
            booking = session.query(InventoryDocumentBooking).filter_by(
                document_id=values["document_id"],
                position_key=values["position_key"],
                movement_kind=values["movement_kind"],
            ).one_or_none()
            if booking is None:
                booking = InventoryDocumentBooking(id=uuid.uuid4(), **values)
                session.add(booking)
            else:
                for key, value in values.items():
                    setattr(booking, key, value)
            session.flush()
            return booking

    def _get_returned_quantity(self, original_document_id: str, original_position_key: str) -> int:
        with session_scope(self._session_factory) as session:
            total = session.query(func.coalesce(func.sum(InventoryDocumentBooking.quantity_applied), 0)).filter_by(
                original_document_id=original_document_id,
                original_position_key=original_position_key,
                movement_kind="return",
            ).scalar()
            return int(total or 0)


__all__ = [
    "InvoiceInventoryBookingResult",
    "InvoiceInventoryBookingService",
    "InvoiceInventoryLine",
]
