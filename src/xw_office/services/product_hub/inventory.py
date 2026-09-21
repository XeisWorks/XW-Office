"""Inventory V2 — shadow-mode ledger, alert crossing, and dealer-summary (PR13/PR14).

**Scope, deliberately limited** (per the build plan's own framing of PR13 as
"Hub-Lagerledger aufbauen, noch ohne finalen Master-Cutover"):

- The append-only ledger (``InventoryRepository.record_movement``), alert crossing
  detection, and the ``/api/v1/inventory/summary`` tile endpoint are fully built and
  usable by new code today.
- **Not done**: none of the legacy inventory call sites (START/Druck, REPRINTS,
  Rechnungs-Fulfillment, manuelle Korrektur, Retouren, Recount, `PrintDecisionEngine`)
  have been rewired to write through this ledger. They keep using the existing
  `SettingKV`-backed `InventoryService` entirely unchanged. Wiring them in is a
  larger, higher-risk refactor of live production code paths that the build plan
  itself does not ask PR13 to complete — it asks PR13 to *inventarisieren*
  (catalogue/identify) those paths, which is done here in this docstring and in
  `docs/product_hub/PROGRESS.md`, not by rewriting them.
- **Not done**: automatic sevdesk stock reading. `PartClient`/`SevdeskConnection`
  require a full desktop `AppConfig`, which the lean web service has deliberately
  never constructed (see `web/app.py`'s existing `_EnvSecretSource` precedent for
  Wix — sevdesk would need the same kind of careful, separately-verified shim, not
  something to rush under time pressure after two near-misses this session already).
  `reconcile_variant_stock` below takes the external stock figure as a parameter
  instead of fetching it live — the comparison/conflict-creation logic is real and
  tested, just not wired to an automatic sevdesk poll yet.
- **Not done**: the actual XW-Flow HTTP integration. There is no XW-Flow API client
  anywhere in this codebase and its contract is undocumented here, so a real HTTP
  call would be fabricated. Instead, a newly-opened alert writes an
  ``inventory_alert.opened`` outbox event with exactly the fields the build plan
  specifies (title/description/notes/planning_mode/external_entity_type/
  external_entity_id/external_deep_link/client_request_id) — the same "wait for a
  real handler" pattern PR10/PR11 already established for Wix before PR11 existed.
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub_inventory import InventoryAlert, InventoryMovement
from xw_office.repositories.product_hub import ProductFilter, ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.repositories.product_hub_sync import SyncRepository, append_outbox_event

DEFAULT_LOCATION_CODE = "MAIN"
DEFAULT_LOCATION_NAME = "Hauptlager"

#: Fixed per the build plan: "client_request_id=UUID5(<namespace>, <alert uuid>)".
_XW_FLOW_NAMESPACE = uuid.UUID("6f6f9f0e-6b0a-4c8e-9a8b-3a6a9a6c9a6a")


class InventorySummary:
    def __init__(
        self,
        *,
        physical_products: int,
        low_stock: int,
        out_of_stock: int,
        open_reprint_alerts: int,
        sync_errors: int,
        updated_at: datetime.datetime,
    ) -> None:
        self.physical_products = physical_products
        self.low_stock = low_stock
        self.out_of_stock = out_of_stock
        self.open_reprint_alerts = open_reprint_alerts
        self.sync_errors = sync_errors
        self.updated_at = updated_at


class MovementResult:
    def __init__(self, movement: InventoryMovement, alert_opened: InventoryAlert | None) -> None:
        self.movement = movement
        self.alert_opened = alert_opened


class InventoryCutoverCheck:
    """One transparent PR15 gate; no gate is inferred from a feature flag alone."""

    def __init__(self, *, code: str, label: str, state: str, detail: str) -> None:
        self.code = code
        self.label = label
        self.state = state
        self.detail = detail


class InventoryCutoverReadiness:
    def __init__(
        self,
        *,
        master_enabled: bool,
        shadow_enabled: bool,
        eligible: bool,
        checks: list[InventoryCutoverCheck],
        assessed_at: datetime.datetime,
    ) -> None:
        self.master_enabled = master_enabled
        self.shadow_enabled = shadow_enabled
        self.eligible = eligible
        self.checks = checks
        self.assessed_at = assessed_at


class InventoryV2Service:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        public_base_url: str = "",
        shadow_enabled: bool = False,
        master_enabled: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._inventory = InventoryRepository(session_factory)
        self._products = ProductHubRepository(session_factory)
        self._sync = SyncRepository(session_factory)
        self._public_base_url = public_base_url.rstrip("/")
        self._shadow_enabled = shadow_enabled
        self._master_enabled = master_enabled

    # -- ledger -----------------------------------------------------------------------

    def record_movement(
        self,
        *,
        variant_id: uuid.UUID,
        delta: int,
        reason: str,
        source: str,
        idempotency_key: str,
        location_code: str = DEFAULT_LOCATION_CODE,
        external_reference: str = "",
        note: str = "",
        actor: str = "",
        occurred_at: datetime.datetime | None = None,
    ) -> MovementResult:
        location = self._inventory.get_or_create_location(
            code=location_code, name=DEFAULT_LOCATION_NAME
        )
        before_stock = self._inventory.get_stock(variant_id, location.id)
        before_on_hand = before_stock.on_hand if before_stock is not None else 0

        movement = self._inventory.record_movement(
            variant_id=variant_id,
            location_id=location.id,
            delta=delta,
            reason=reason,
            source=source,
            idempotency_key=idempotency_key,
            external_reference=external_reference,
            note=note,
            actor=actor,
            occurred_at=occurred_at,
        )

        alert_opened = self._apply_alert_crossing(
            variant_id, location.id, before_on_hand, movement.on_hand_after
        )
        if alert_opened is not None:
            self._emit_flow_task_intent(alert_opened, variant_id)
        return MovementResult(movement=movement, alert_opened=alert_opened)

    def _apply_alert_crossing(
        self, variant_id: uuid.UUID, location_id: uuid.UUID, before: int, after: int
    ) -> InventoryAlert | None:
        """``before > threshold AND after <= threshold`` per the build plan's exact
        crossing rule; resolves any open alert once stock is back above threshold."""
        stock = self._inventory.get_stock(variant_id, location_id)
        threshold = stock.reorder_point if stock is not None else 0

        if before > threshold and after <= threshold:
            alert_type = "out_of_stock" if after <= 0 else "low_stock"
            already_open = self._inventory.get_open_alert(variant_id, location_id, alert_type)
            alert = self._inventory.open_or_update_alert(
                variant_id=variant_id,
                location_id=location_id,
                alert_type=alert_type,
                threshold=threshold,
                observed_stock=after,
            )
            return None if already_open is not None else alert

        if after > threshold:
            for alert_type in ("low_stock", "out_of_stock"):
                open_alert = self._inventory.get_open_alert(variant_id, location_id, alert_type)
                if open_alert is not None:
                    self._inventory.resolve_alert(open_alert.id)
        return None

    def _emit_flow_task_intent(self, alert: InventoryAlert, variant_id: uuid.UUID) -> None:
        variant = self._products.get_variant(variant_id)
        if variant is None:
            return
        product = self._products.get_product(variant.product_id)
        if product is None:
            return
        open_improvements = [
            imp.title or imp.description
            for imp in self._products.list_improvements(product.id)
            if imp.status == "open"
        ]
        client_request_id = uuid.uuid5(_XW_FLOW_NAMESPACE, str(alert.id))
        payload = {
            "title": f"Nachdruck: {variant.sku} – {product.name}",
            "description": "Lagerwarnung",
            "notes": (
                f"Bestand: {alert.observed_stock}, Schwelle: {alert.threshold}, "
                f"Zielbestand: n/a, offene Verbesserungen: {'; '.join(open_improvements) or 'keine'}"
            ),
            "planning_mode": "PIPELINE",
            "external_entity_type": "inventory_alert",
            "external_entity_id": str(alert.id),
            "external_deep_link": f"{self._public_base_url}/app/products/{product.id}",
            "client_request_id": str(client_request_id),
        }
        with session_scope(self._session_factory) as session:
            append_outbox_event(
                session,
                aggregate_type="inventory_alert",
                aggregate_id=alert.id,
                event_type="inventory_alert.opened",
                payload=payload,
            )

    # -- shadow reconcile (sevdesk stock supplied by the caller, not fetched live) -----

    def reconcile_variant_stock(
        self, variant_id: uuid.UUID, *, sevdesk_on_hand: int, location_code: str = DEFAULT_LOCATION_CODE
    ) -> bool:
        """Compare Hub on_hand against a caller-supplied sevdesk figure; records a
        `sync_conflict` (not a silent correction — shadow mode never writes stock from
        this comparison) if they differ and none is already open. Returns whether a
        (new or already-open) drift exists."""
        location = self._inventory.get_or_create_location(
            code=location_code, name=DEFAULT_LOCATION_NAME
        )
        stock = self._inventory.get_stock(variant_id, location.id)
        hub_on_hand = stock.on_hand if stock is not None else 0
        if hub_on_hand == sevdesk_on_hand:
            return False

        existing = self._sync.get_open_conflict(
            channel="sevdesk",
            entity_type="inventory_stock",
            internal_entity_id=variant_id,
            field_name="on_hand",
        )
        if existing is None:
            self._sync.create_sync_conflict(
                channel="sevdesk",
                entity_type="inventory_stock",
                internal_entity_id=variant_id,
                field_name="on_hand",
                hub_value=str(hub_on_hand),
                external_value=str(sevdesk_on_hand),
            )
        return True

    # -- summary tile (PR14 GET /api/v1/inventory/summary) ----------------------------

    def compute_summary(self) -> InventorySummary:
        products = self._products.list_products(ProductFilter(status="live", active=True))
        physical_products = sum(1 for p in products if p.product_type == "physical")

        open_alerts = self._inventory.list_open_alerts()
        low_stock = sum(1 for a in open_alerts if a.type == "low_stock")
        out_of_stock = sum(1 for a in open_alerts if a.type == "out_of_stock")

        sync_errors = len(self._sync.list_open_sync_conflicts())

        return InventorySummary(
            physical_products=physical_products,
            low_stock=low_stock,
            out_of_stock=out_of_stock,
            open_reprint_alerts=low_stock + out_of_stock,
            sync_errors=sync_errors,
            updated_at=datetime.datetime.now(datetime.timezone.utc),
        )

    # -- PR15 cutover readiness -------------------------------------------------------

    def cutover_readiness(self) -> InventoryCutoverReadiness:
        """Report the evidence required before Product Hub may become stock master.

        This deliberately does not enable the master flag and does not turn a lack of
        observed drift into approval.  Several PR15 prerequisites are operational
        facts (backups, a representative shadow interval and a rollback rehearsal),
        so the report labels them as manual gates instead of pretending that code can
        certify them.
        """
        movement_count = self._inventory.count_movements()
        stock_positions = self._inventory.count_stock_rows()
        open_inventory_drifts = [
            conflict
            for conflict in self._sync.list_open_sync_conflicts(channel="sevdesk")
            if conflict.entity_type == "inventory_stock" and conflict.field_name == "on_hand"
        ]
        all_open_sync_conflicts = self._sync.list_open_sync_conflicts()
        checks = [
            InventoryCutoverCheck(
                code="shadow_mode",
                label="Shadow Mode ist aktiv",
                state="ready" if self._shadow_enabled else "blocked",
                detail=(
                    "Der Ledger darf im Shadow Mode Daten sammeln."
                    if self._shadow_enabled
                    else "XW_PRODUCT_HUB_INVENTORY_SHADOW_ENABLED ist nicht aktiviert."
                ),
            ),
            InventoryCutoverCheck(
                code="ledger_evidence",
                label="Inventory-V2-Ledger enthält reale Bewegungen",
                state="ready" if movement_count > 0 and stock_positions > 0 else "blocked",
                detail=f"{movement_count} Ledger-Bewegungen, {stock_positions} Bestandspositionen erfasst.",
            ),
            InventoryCutoverCheck(
                code="sevdesk_drift",
                label="sevdesk-/Hub-Drift ist bereinigt",
                state="ready" if movement_count > 0 and not open_inventory_drifts else "blocked",
                detail=(
                    "Keine offene Inventory-Drift in der Sync-Queue."
                    if not open_inventory_drifts
                    else f"{len(open_inventory_drifts)} offene Inventory-Drift-Konflikte."
                ),
            ),
            InventoryCutoverCheck(
                code="legacy_mutation_paths",
                label="Alle Bestandsänderungen laufen durch Inventory V2",
                state="blocked",
                detail=(
                    "Noch offen: START/REPRINTS, Rechnungs-Fulfillment, manuelle Korrektur, "
                    "Retouren/Recount und PrintDecisionEngine verwenden weiterhin Legacy-Pfade."
                ),
            ),
            InventoryCutoverCheck(
                code="channel_projections",
                label="Wix- und sevdesk-Bestandsprojektionen sind getestet",
                state="blocked",
                detail="Die PR15-Projektionsadapter sind noch nicht implementiert.",
            ),
            InventoryCutoverCheck(
                code="sync_queue",
                label="Keine ungeklärten Sync-Fehler",
                state="ready" if not all_open_sync_conflicts else "blocked",
                detail=(
                    "Die Sync-Queue ist leer."
                    if not all_open_sync_conflicts
                    else f"{len(all_open_sync_conflicts)} offene Sync-Konflikte erfordern Prüfung."
                ),
            ),
            InventoryCutoverCheck(
                code="operational_signoff",
                label="Backups, repräsentative Shadow-Phase und Rollback sind bestätigt",
                state="manual",
                detail=(
                    "Muss außerhalb der Anwendung durch den Betriebsverantwortlichen "
                    "bestätigt und dokumentiert werden."
                ),
            ),
        ]
        eligible = all(check.state == "ready" for check in checks)
        return InventoryCutoverReadiness(
            master_enabled=self._master_enabled,
            shadow_enabled=self._shadow_enabled,
            eligible=eligible,
            checks=checks,
            assessed_at=datetime.datetime.now(datetime.timezone.utc),
        )
