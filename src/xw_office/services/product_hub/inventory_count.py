"""Guided, idempotent physical inventory counting for the Product Hub."""
from __future__ import annotations

from dataclasses import dataclass
import datetime
import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import Product, ProductVariant
from xw_office.models.product_hub_inventory import InventoryStock
from xw_office.models.inventory_count import InventoryCountLine, InventoryCountSession
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.services.product_hub.inventory import DEFAULT_LOCATION_CODE, InventoryV2Service


@dataclass(frozen=True)
class InventoryCountLineView:
    id: uuid.UUID
    variant_id: uuid.UUID
    sku: str
    title: str
    location_code: str
    system_quantity: int
    counted_quantity: int | None
    difference: int | None
    status: str
    note: str
    movement_id: uuid.UUID | None


@dataclass(frozen=True)
class InventoryCountView:
    id: uuid.UUID
    status: str
    location_code: str
    started_at: datetime.datetime
    confirmed_at: datetime.datetime | None
    baseline_source_hash: str
    lines: list[InventoryCountLineView]


class InventoryCountService:
    """Create a frozen SKU count list and commit each confirmed difference once."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._inventory = InventoryV2Service(session_factory)
        self._repository = InventoryRepository(session_factory)

    def start(self, *, location_code: str = DEFAULT_LOCATION_CODE) -> InventoryCountView:
        location = self._repository.get_or_create_location(code=location_code, name="Hauptlager")
        with session_scope(self._session_factory) as session:
            variants = list(
                session.scalars(
                    select(ProductVariant, Product)
                    .join(Product, Product.id == ProductVariant.product_id)
                    .where(ProductVariant.active.is_(True), ProductVariant.stock_enabled.is_(True), Product.active.is_(True))
                    .order_by(ProductVariant.sku)
                ).all()
            )
            # SQLAlchemy's scalar() returns ProductVariant for the two-entity select;
            # load parent rows explicitly for the title/article-kind filter below.
            rows: list[tuple[ProductVariant, Product]] = []
            for variant in variants:
                product = session.get(Product, variant.product_id)
                if product is None:
                    continue
                article_kind = str((variant.attributes or {}).get("article_kind") or (product.attributes or {}).get("article_kind") or "external_print").lower()
                if article_kind == "digital" or product.product_type == "digital":
                    continue
                rows.append((variant, product))
            count = InventoryCountSession(
                id=uuid.uuid4(), status="draft", location_code=location_code,
                started_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(count)
            session.flush()
            snapshot: list[dict[str, object]] = []
            for variant, product in rows:
                stock = session.get(InventoryStock, (variant.id, location.id))
                system_quantity = int(stock.on_hand if stock is not None else 0)
                title = str(variant.name or product.name or variant.sku)
                line = InventoryCountLine(
                    id=uuid.uuid4(), session_id=count.id, variant_id=variant.id,
                    location_code=location_code, sku=variant.sku, title=title,
                    system_quantity=system_quantity,
                )
                session.add(line)
                snapshot.append({"sku": variant.sku, "variant_id": str(variant.id), "system_quantity": system_quantity})
            count.baseline_source_hash = hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            session.flush()
            count_id = count.id
        return self.get(count_id)

    def get(self, count_id: uuid.UUID) -> InventoryCountView:
        with session_scope(self._session_factory) as session:
            count = session.get(InventoryCountSession, count_id)
            if count is None:
                raise KeyError(f"Inventur {count_id} nicht gefunden")
            lines = list(
                session.scalars(
                    select(InventoryCountLine).where(InventoryCountLine.session_id == count_id).order_by(InventoryCountLine.sku)
                ).all()
            )
            return InventoryCountView(
                id=count.id, status=count.status, location_code=count.location_code,
                started_at=count.started_at, confirmed_at=count.confirmed_at,
                baseline_source_hash=count.baseline_source_hash,
                lines=[self._line_view(line) for line in lines],
            )

    def record_count(self, *, count_id: uuid.UUID, line_id: uuid.UUID, counted_quantity: int, note: str = "") -> InventoryCountLineView:
        if counted_quantity < 0:
            raise ValueError("Gezählte Menge darf nicht negativ sein")
        with session_scope(self._session_factory) as session:
            count = session.get(InventoryCountSession, count_id)
            line = session.get(InventoryCountLine, line_id)
            if count is None or line is None or line.session_id != count_id:
                raise KeyError("Inventurzeile nicht gefunden")
            if count.status != "draft":
                raise ValueError("Bestätigte Inventuren sind unveränderlich")
            line.counted_quantity = counted_quantity
            line.difference = counted_quantity - line.system_quantity
            line.status = "counted"
            line.note = note.strip()
            line.counted_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return self._line_view(line)

    def confirm(self, *, count_id: uuid.UUID, actor: str = "") -> InventoryCountView:
        view = self.get(count_id)
        if view.status != "draft":
            return view
        if any(line.counted_quantity is None for line in view.lines):
            raise ValueError("Alle Inventurzeilen müssen gezählt und geprüft sein")
        for line in view.lines:
            location = self._repository.get_location_by_code(view.location_code)
            current_stock = self._repository.get_stock(line.variant_id, location.id) if location is not None else None
            # Use the latest ledger value at confirmation time so sales or print
            # movements made while counting are not silently overwritten.
            current_quantity = int(current_stock.on_hand if current_stock is not None else 0)
            delta = int(line.counted_quantity or 0) - current_quantity
            if delta:
                result = self._inventory.record_movement(
                    variant_id=line.variant_id,
                    delta=delta,
                    reason="recount",
                    source="guided_inventory",
                    idempotency_key=f"inventory-count:{count_id}:{line.id}",
                    location_code=view.location_code,
                    external_reference=str(count_id),
                    note=line.note or "Inventurabschluss",
                    actor=actor,
                )
                with session_scope(self._session_factory) as session:
                    db_line = session.get(InventoryCountLine, line.id)
                    if db_line is not None:
                        db_line.difference = delta
                        db_line.movement_id = result.movement.id
                        db_line.status = "applied"
            else:
                with session_scope(self._session_factory) as session:
                    db_line = session.get(InventoryCountLine, line.id)
                    if db_line is not None:
                        db_line.difference = 0
                        db_line.status = "applied"
        with session_scope(self._session_factory) as session:
            count = session.get(InventoryCountSession, count_id)
            if count is not None:
                count.status = "confirmed"
                count.confirmed_at = datetime.datetime.now(datetime.timezone.utc)
                count.counted_at = count.confirmed_at
                count.confirmed_by = actor
        return self.get(count_id)

    @staticmethod
    def _line_view(line: InventoryCountLine) -> InventoryCountLineView:
        return InventoryCountLineView(
            id=line.id, variant_id=line.variant_id, sku=line.sku, title=line.title,
            location_code=line.location_code, system_quantity=line.system_quantity,
            counted_quantity=line.counted_quantity, difference=line.difference,
            status=line.status, note=line.note, movement_id=line.movement_id,
        )


__all__ = ["InventoryCountLineView", "InventoryCountService", "InventoryCountView"]
