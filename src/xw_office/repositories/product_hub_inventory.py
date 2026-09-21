"""Repository layer for the Inventory V2 ledger (PR13/PR14, shadow mode).

Every stock change goes through :meth:`InventoryRepository.record_movement` — the
only writer of ``inventory_stock.on_hand``. Never mutated directly, per the data
model's "changed only through InventoryService ledger transactions" rule (this
repository *is* that ledger transaction boundary for Inventory V2 specifically; the
legacy ``InventoryService`` is untouched — see ``services/product_hub/inventory.py``).
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime
import uuid
from collections.abc import Generator

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub_inventory import (
    InventoryAlert,
    InventoryLocation,
    InventoryMovement,
    InventoryStock,
)


class NegativeStockError(ValueError):
    """Raised when a movement would drive ``on_hand`` below zero."""


class InventoryRepository:
    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    # -- locations --------------------------------------------------------------------

    def get_or_create_location(self, *, code: str, name: str) -> InventoryLocation:
        with self._scope() as session:
            existing = session.scalar(
                select(InventoryLocation).where(InventoryLocation.code == code)
            )
            if existing is not None:
                return existing
            location = InventoryLocation(id=uuid.uuid4(), code=code, name=name)
            session.add(location)
            session.flush()
            return location

    def get_location_by_code(self, code: str) -> InventoryLocation | None:
        with self._scope() as session:
            return session.scalar(select(InventoryLocation).where(InventoryLocation.code == code))

    def list_locations(self) -> list[InventoryLocation]:
        with self._scope() as session:
            return list(session.scalars(select(InventoryLocation)).all())

    # -- stock / movements --------------------------------------------------------------

    def get_stock(self, variant_id: uuid.UUID, location_id: uuid.UUID) -> InventoryStock | None:
        with self._scope() as session:
            return session.get(InventoryStock, (variant_id, location_id))

    def set_stock_thresholds(
        self,
        variant_id: uuid.UUID,
        location_id: uuid.UUID,
        *,
        reorder_point: int | None = None,
        target_stock: int | None = None,
        default_reprint_qty: int | None = None,
    ) -> InventoryStock:
        with self._scope() as session:
            stock = session.get(InventoryStock, (variant_id, location_id))
            if stock is None:
                stock = InventoryStock(variant_id=variant_id, location_id=location_id)
                session.add(stock)
            if reorder_point is not None:
                stock.reorder_point = reorder_point
            if target_stock is not None:
                stock.target_stock = target_stock
            if default_reprint_qty is not None:
                stock.default_reprint_qty = default_reprint_qty
            session.flush()
            return stock

    def get_movement_by_idempotency_key(self, idempotency_key: str) -> InventoryMovement | None:
        with self._scope() as session:
            return session.scalar(
                select(InventoryMovement).where(
                    InventoryMovement.idempotency_key == idempotency_key
                )
            )

    def record_movement(
        self,
        *,
        variant_id: uuid.UUID,
        location_id: uuid.UUID,
        delta: int,
        reason: str,
        source: str,
        idempotency_key: str,
        external_reference: str = "",
        note: str = "",
        actor: str = "",
        occurred_at: datetime.datetime | None = None,
    ) -> InventoryMovement:
        """Append one ledger entry and update the materialized stock row atomically.

        Idempotent: a repeated call with the same ``idempotency_key`` returns the
        existing movement unchanged rather than applying the delta twice — required
        for safe retries from any caller (PR15's precondition #7, "Inventory-
        Movement-Idempotency getestet", is exercised here even though this PR doesn't
        attempt the cutover itself).
        """
        with self._scope() as session:
            existing = session.scalar(
                select(InventoryMovement).where(
                    InventoryMovement.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return existing

            stock = session.get(InventoryStock, (variant_id, location_id))
            if stock is None:
                stock = InventoryStock(variant_id=variant_id, location_id=location_id, on_hand=0)
                session.add(stock)
                session.flush()

            on_hand_after = stock.on_hand + delta
            if on_hand_after < 0:
                raise NegativeStockError(
                    f"Movement would drive on_hand to {on_hand_after} "
                    f"(variant={variant_id}, location={location_id}, delta={delta})"
                )
            stock.on_hand = on_hand_after
            stock.version += 1

            movement = InventoryMovement(
                id=uuid.uuid4(),
                variant_id=variant_id,
                location_id=location_id,
                delta=delta,
                reason=reason,
                source=source,
                external_reference=external_reference or None,
                idempotency_key=idempotency_key,
                note=note or None,
                on_hand_after=on_hand_after,
                actor=actor or None,
                occurred_at=occurred_at or datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(movement)
            session.flush()
            return movement

    def list_movements(
        self, variant_id: uuid.UUID, location_id: uuid.UUID, *, limit: int = 100
    ) -> list[InventoryMovement]:
        with self._scope() as session:
            stmt = (
                select(InventoryMovement)
                .where(
                    InventoryMovement.variant_id == variant_id,
                    InventoryMovement.location_id == location_id,
                )
                .order_by(InventoryMovement.occurred_at.desc())
                .limit(limit)
            )
            return list(session.scalars(stmt).all())

    def count_movements(self) -> int:
        """Return the number of recorded Inventory V2 ledger events."""
        with self._scope() as session:
            return int(session.scalar(select(func.count()).select_from(InventoryMovement)) or 0)

    def count_movements_for_variant(self, variant_id: uuid.UUID) -> int:
        """Return ledger events for one variant, used to prevent re-baselining it."""
        with self._scope() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(InventoryMovement.variant_id == variant_id)
                )
                or 0
            )

    def count_stock_rows(self) -> int:
        """Return materialized Inventory V2 stock positions across all locations."""
        with self._scope() as session:
            return int(session.scalar(select(func.count()).select_from(InventoryStock)) or 0)

    # -- alerts ---------------------------------------------------------------------

    def get_open_alert(
        self, variant_id: uuid.UUID, location_id: uuid.UUID, alert_type: str
    ) -> InventoryAlert | None:
        with self._scope() as session:
            return session.scalar(
                select(InventoryAlert).where(
                    InventoryAlert.variant_id == variant_id,
                    InventoryAlert.location_id == location_id,
                    InventoryAlert.type == alert_type,
                    InventoryAlert.status == "open",
                )
            )

    def open_or_update_alert(
        self,
        *,
        variant_id: uuid.UUID,
        location_id: uuid.UUID,
        alert_type: str,
        threshold: int | None,
        observed_stock: int | None,
    ) -> InventoryAlert:
        """Idempotent per the PR14 dedupe rule: while an alert is open, re-crossing
        the same threshold updates it in place rather than creating a duplicate."""
        with self._scope() as session:
            existing = session.scalar(
                select(InventoryAlert).where(
                    InventoryAlert.variant_id == variant_id,
                    InventoryAlert.location_id == location_id,
                    InventoryAlert.type == alert_type,
                    InventoryAlert.status == "open",
                )
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            if existing is not None:
                existing.last_triggered_at = now
                existing.observed_stock = observed_stock
                existing.threshold = threshold
                session.flush()
                return existing
            alert = InventoryAlert(
                id=uuid.uuid4(),
                variant_id=variant_id,
                location_id=location_id,
                type=alert_type,
                status="open",
                threshold=threshold,
                observed_stock=observed_stock,
                first_triggered_at=now,
                last_triggered_at=now,
            )
            session.add(alert)
            session.flush()
            return alert

    def resolve_alert(self, alert_id: uuid.UUID) -> InventoryAlert:
        with self._scope() as session:
            alert = session.get(InventoryAlert, alert_id)
            if alert is None:
                raise KeyError(f"Inventory alert {alert_id} not found")
            alert.status = "resolved"
            alert.resolved_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return alert

    def set_alert_flow_task(
        self, alert_id: uuid.UUID, *, xw_flow_task_id: uuid.UUID, xw_flow_client_request_id: uuid.UUID
    ) -> InventoryAlert:
        with self._scope() as session:
            alert = session.get(InventoryAlert, alert_id)
            if alert is None:
                raise KeyError(f"Inventory alert {alert_id} not found")
            alert.xw_flow_task_id = xw_flow_task_id
            alert.xw_flow_client_request_id = xw_flow_client_request_id
            session.flush()
            return alert

    def list_open_alerts(self) -> list[InventoryAlert]:
        with self._scope() as session:
            stmt = select(InventoryAlert).where(InventoryAlert.status == "open")
            return list(session.scalars(stmt).all())

    def get_alert(self, alert_id: uuid.UUID) -> InventoryAlert | None:
        with self._scope() as session:
            return session.get(InventoryAlert, alert_id)
