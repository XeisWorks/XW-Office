"""Idempotent inventory booking for finalized invoice document positions."""
from __future__ import annotations

from contextlib import nullcontext
from collections.abc import Iterable
from dataclasses import dataclass
import uuid
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.inventory_document_booking import InventoryDocumentBooking
from xw_office.models.product_hub_inventory import InventoryAlert
from xw_office.repositories.product_hub import ProductHubRepository, ResolvedSku
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.invoice_processing.context import InvoiceWorkPosition


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

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._inventory = InventoryV2Service(session_factory)
        self._repository = InventoryRepository(session_factory)
        self._products = ProductHubRepository(session_factory)

    def apply_invoice_context(
        self,
        *,
        document_id: str,
        positions: Iterable[InvoiceWorkPosition],
        source: str = "sevdesk.invoice_release",
    ) -> list[InvoiceInventoryBookingResult]:
        """Book resolvable physical product positions from a normalized context.

        Digital, service, shipping, discount, and unknown positions are ignored by
        design.  A product-like position without an exact Hub SKU raises so a final
        invoice cannot silently disappear from inventory accounting.
        """
        results: list[InvoiceInventoryBookingResult] = []
        for position in self._resolve_invoice_lines(positions):
            resolved, quantity, position_key = position
            results.append(
                self.apply_line(
                    InvoiceInventoryLine(
                        document_id=document_id,
                        position_key=position_key,
                        variant_id=resolved.variant.id,
                        quantity=quantity,
                        movement_kind="sale",
                    ),
                    source=source,
                )
            )
        return results

    def validate_invoice_context(self, positions: Iterable[InvoiceWorkPosition]) -> None:
        """Resolve all physical product positions before an external finalization."""
        self._resolve_invoice_lines(positions)

    def resolve_physical_sku(self, sku: str) -> ResolvedSku | None:
        """Expose exact SKU resolution to conservative external feed adapters."""
        resolved = self._products.resolve_sku(sku)
        if resolved is None or not resolved.variant.active or not resolved.variant.stock_enabled:
            return None
        return resolved

    def sku_for_variant(self, variant_id: uuid.UUID) -> str:
        """Return the canonical SKU for an already-resolved booking variant."""
        variant = self._products.get_variant(variant_id)
        return str(variant.sku if variant is not None else "").strip().upper()

    def _resolve_invoice_lines(
        self, positions: Iterable[InvoiceWorkPosition]
    ) -> list[tuple[ResolvedSku, int, str]]:
        unresolved: list[str] = []
        resolved_lines: list[tuple[ResolvedSku, int, str]] = []
        for position in positions:
            if getattr(position, "kind", "") != "product":
                continue
            quantity_is_integer = getattr(position, "quantity_is_integer", True)
            sku = str(getattr(position, "sku", "") or "").strip().upper()
            quantity = getattr(position, "quantity_int", 0)
            if quantity <= 0 and quantity_is_integer:
                continue
            if not sku:
                unresolved.append("<ohne SKU>")
                continue
            resolved = self._products.resolve_sku(sku)
            if resolved is None or not resolved.variant.active:
                unresolved.append(sku or "<ohne SKU>")
                continue
            if not resolved.variant.stock_enabled:
                continue
            if not quantity_is_integer:
                raise ValueError("Physische Rechnungsposition enthält eine Bruchmenge")
            resolved_lines.append(
                (
                    resolved,
                    int(quantity),
                    str(getattr(position, "source_id", "") or "").strip()
                    or f"position-{getattr(position, 'position_number', 0)}",
                )
            )
        if unresolved:
            raise ValueError(
                "Physische Rechnungspositionen ohne eindeutige Product-Hub-Variante: "
                + ", ".join(sorted(set(unresolved)))
            )
        return resolved_lines

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
        if line.quantity < 0:
            raise ValueError("quantity must not be negative")
        deferred_alerts: list[InventoryAlert] = []
        with session_scope(self._session_factory) as session:
            sale = session.execute(
                select(InventoryDocumentBooking)
                .filter_by(
                    document_id=original_document_id,
                    position_key=original_position_key,
                    movement_kind="sale",
                )
                .with_for_update()
            ).scalar_one_or_none()
            if sale is None or sale.quantity_applied >= 0:
                raise ValueError("No booked sale position exists for this credit")
            existing_return = session.execute(
                select(InventoryDocumentBooking)
                .filter_by(
                    document_id=line.document_id,
                    position_key=line.position_key,
                    movement_kind="return",
                )
                .with_for_update()
            ).scalar_one_or_none()
            total_returned = session.query(func.coalesce(
                func.sum(InventoryDocumentBooking.quantity_applied), 0
            )).filter_by(
                original_document_id=original_document_id,
                original_position_key=original_position_key,
                movement_kind="return",
            ).scalar()
            already_returned = existing_return.quantity_applied if existing_return is not None else 0
            other_returned = max(0, int(total_returned or 0) - already_returned)
            max_return = max(0, -sale.quantity_applied - other_returned)
            if line.quantity > max_return:
                raise ValueError(
                    f"Credit quantity {line.quantity} exceeds remaining returnable quantity {max_return}"
                )
            result = self.apply_line(
                line,
                source=source,
                _session=session,
                _deferred_alerts=deferred_alerts,
            )
        for alert in deferred_alerts:
            self._inventory._emit_flow_task_intent(alert, line.variant_id)
        return result

    def apply_line(
        self,
        line: InvoiceInventoryLine,
        *,
        source: str = "sevdesk.invoice_release",
        _session: Session | None = None,
        _deferred_alerts: list[InventoryAlert] | None = None,
    ) -> InvoiceInventoryBookingResult:
        document_id = str(line.document_id or "").strip()
        position_key = str(line.position_key or "").strip()
        if not document_id or not position_key:
            raise ValueError("document_id und position_key sind erforderlich")
        if line.quantity < 0:
            raise ValueError("quantity darf nicht negativ sein")
        if line.movement_kind not in {"sale", "return"}:
            raise ValueError("movement_kind muss sale oder return sein")
        signed_target = -line.quantity if line.movement_kind == "sale" else line.quantity
        opened_alert = None
        scope = session_scope(self._session_factory) if _session is None else nullcontext(_session)
        with scope as session:
            identity = {
                "document_id": document_id,
                "position_key": position_key,
                "movement_kind": line.movement_kind,
            }
            self._ensure_booking_row(session, identity, line)
            booking = session.execute(
                select(InventoryDocumentBooking)
                .filter_by(**identity)
                .with_for_update()
            ).scalar_one()
            previous = booking.quantity_applied
            delta = signed_target - previous
            movement_id = None
            if delta:
                revision = self._next_transition_revision(booking.last_idempotency_key)
                key = (
                    f"invoice-line:{document_id}:{position_key}:"
                    f"{line.movement_kind}:revision:{revision}"
                )
                movement = self._inventory.record_movement(
                    variant_id=line.variant_id,
                    delta=delta,
                    reason=line.movement_kind,
                    source=source,
                    idempotency_key=key,
                    external_reference=f"{document_id}:{position_key}",
                    note="finalized document position",
                    session=session,
                )
                movement_id = movement.movement.id
                booking.variant_id = line.variant_id
                booking.quantity_applied = signed_target
                booking.source_revision = line.source_revision
                booking.last_idempotency_key = key
                booking.original_document_id = line.original_document_id
                booking.original_position_key = line.original_position_key
                opened_alert = movement.alert_opened
                status = "applied"
            else:
                status = "already_applied"
        if opened_alert is not None and _deferred_alerts is not None:
            _deferred_alerts.append(opened_alert)
        elif opened_alert is not None and _session is None:
            self._inventory._emit_flow_task_intent(opened_alert, line.variant_id)
        return InvoiceInventoryBookingResult(
            document_id=document_id,
            position_key=position_key,
            previous_quantity_applied=previous,
            requested_quantity_applied=signed_target,
            delta=delta,
            movement_id=movement_id,
            status=status,
        )

    @staticmethod
    def _next_transition_revision(last_key: str) -> int:
        marker = ":revision:"
        if marker not in last_key:
            return 1
        try:
            return int(last_key.rsplit(marker, 1)[1]) + 1
        except ValueError:
            return 1

    @staticmethod
    def _ensure_booking_row(
        session: Session, identity: dict[str, str], line: InvoiceInventoryLine
    ) -> None:
        """Create the row before locking it so first-booking races serialize."""
        table = cast(Table, InventoryDocumentBooking.__table__)
        values = {
            **identity,
            "id": uuid.uuid4(),
            "variant_id": line.variant_id,
            "quantity_applied": 0,
            "source_revision": "",
            "last_idempotency_key": "",
            "original_document_id": line.original_document_id,
            "original_position_key": line.original_position_key,
        }
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            session.execute(pg_insert(table).values(**values).on_conflict_do_nothing(
                constraint="uq_inventory_document_booking_position"
            ))
        elif dialect == "sqlite":
            session.execute(sqlite_insert(table).values(**values).on_conflict_do_nothing(
                index_elements=["document_id", "position_key", "movement_kind"]
            ))
        else:
            found = session.execute(select(InventoryDocumentBooking.id).filter_by(**identity)).first()
            if found is None:
                session.add(InventoryDocumentBooking(**values))
                session.flush()

__all__ = [
    "InvoiceInventoryBookingResult",
    "InvoiceInventoryBookingService",
    "InvoiceInventoryLine",
]
