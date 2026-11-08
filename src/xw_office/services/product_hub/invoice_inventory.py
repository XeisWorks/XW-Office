"""Idempotent inventory booking for finalized invoice document positions."""
from __future__ import annotations

from dataclasses import dataclass
import uuid

from xw_office.core.database import session_scope
from xw_office.models.inventory_document_booking import InventoryDocumentBooking
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


__all__ = [
    "InvoiceInventoryBookingResult",
    "InvoiceInventoryBookingService",
    "InvoiceInventoryLine",
]
