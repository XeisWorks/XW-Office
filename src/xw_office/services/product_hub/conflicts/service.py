"""Application service for scan, decision, dry-run and audited apply."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import AuditLog, ChannelMapping, Product, ProductVariant
from xw_office.models.product_hub_conflicts import (
    ConflictAction,
    ConflictCase,
    ConflictField,
    ConflictObservation,
)
from xw_office.models.product_hub_sync import OutboxEvent, SyncConflict
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_conflicts import (
    ConflictOptimisticLockError,
    ConflictRepository,
)
from xw_office.repositories.product_hub_sync import append_outbox_event
from xw_office.services.product_hub.conflicts.classifier import classify
from xw_office.services.product_hub.conflicts.normalizer import equivalent, normalize_value
from xw_office.services.wix.identifiers import canonical_wix_id

_TERMINAL_INTENTIONAL = {"INTENTIONAL_DIFFERENCE", "IGNORE"}
_PRODUCT_FIELDS = {
    "name",
    "short_description",
    "description",
    "category",
    "brand_name",
    "status",
    "active",
}
_WIX_TO_HUB = {"name": "name", "description": "description", "visible": "active"}


class FieldBundle(TypedDict):
    field: ConflictField
    observations: list[ConflictObservation]


class DetailBundle(TypedDict):
    case: ConflictCase
    product: Product
    fields: list[FieldBundle]
    actions: list[ConflictAction]


class UnsupportedConflictAction(RuntimeError):
    pass


class StaleConflictError(RuntimeError):
    pass


class ConflictWizardService:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self._repo = ConflictRepository(factory)
        self._products = ProductHubRepository(factory)

    @property
    def repository(self) -> ConflictRepository:
        return self._repo

    def scan_low_level_conflicts(self, *, product_id: uuid.UUID | None = None) -> dict[str, object]:
        scan = self._repo.start_scan(
            scan_type="single_product" if product_id else "full",
            source_scope=["sync_conflict"],
            product_scope={"product_id": str(product_id)} if product_id else {},
        )
        created = updated = differences = 0
        seen: set[uuid.UUID] = set()
        with session_scope(self._factory) as session:
            conflicts = list(
                session.scalars(
                    select(SyncConflict).where(SyncConflict.resolved_at.is_(None))
                ).all()
            )
            for low in conflicts:
                product, variant = _resolve_owner(session, low)
                if product is None or (product_id is not None and product.id != product_id):
                    continue
                if _not_relevant(product, low, self._products):
                    continue
                hub_field = _WIX_TO_HUB.get(low.field_name, low.field_name)
                if equivalent(hub_field, low.hub_value, low.external_value):
                    continue
                differences += 1
                seen.add(low.id)
                ctype, severity, score = classify(hub_field, low.channel)
                dedupe = "|".join(
                    (
                        str(product.id),
                        str(variant.id) if variant else "-",
                        ctype,
                        hub_field,
                        low.channel,
                    )
                )
                case = self._repo.get_active_case(dedupe)
                if case is None:
                    latest = self._repo.latest_case(dedupe)
                    if latest is not None and latest.resolution_type == "INTENTIONAL_DIFFERENCE":
                        continue
                    case = self._repo.create_case(
                        product_id=product.id,
                        variant_id=variant.id if variant else None,
                        origin_sync_conflict_id=low.id,
                        conflict_type=ctype,
                        severity=severity,
                        status="OPEN",
                        priority_score=score,
                        title=f"{variant.sku if variant is not None else product.sku} · {hub_field}",
                        summary=_conflict_summary(low.field_name, low.channel, low.external_value),
                        detected_at=low.detected_at,
                        last_seen_at=_now(),
                        source_scan_id=scan.id,
                        dedupe_key=dedupe,
                        hub_row_version=product.row_version,
                    )
                    created += 1
                else:
                    self._repo.touch_case(
                        case.id,
                        scan_id=scan.id,
                        severity=severity,
                        priority_score=score,
                        hub_row_version=product.row_version,
                        summary=_conflict_summary(low.field_name, low.channel, low.external_value),
                    )
                    updated += 1
                field = self._repo.get_or_create_field(case.id, hub_field)
                self._repo.add_observation(
                    field.id,
                    source="hub",
                    raw_value=low.hub_value,
                    normalized_value=normalize_value(hub_field, low.hub_value),
                )
                self._repo.add_observation(
                    field.id,
                    source=low.channel,
                    raw_value=low.external_value,
                    normalized_value=normalize_value(hub_field, low.external_value),
                    source_revision=_revision(low),
                )
        obsolete = (
            0 if product_id else self._repo.obsolete_unseen(scan_id=scan.id, source_sync_ids=seen)
        )
        finished = self._repo.finish_scan(
            scan.id,
            products_scanned=len({str(c.internal_entity_id) for c in conflicts}),
            differences_found=differences,
            cases_created=created,
            cases_updated=updated,
        )
        return {
            "id": finished.id,
            "differences_found": differences,
            "cases_created": created,
            "cases_updated": updated,
            "cases_obsoleted": obsolete,
        }

    def detail(self, case_id: uuid.UUID) -> DetailBundle:
        case = self._repo.get_case(case_id)
        if case is None:
            raise KeyError(f"Conflict case {case_id} not found")
        with session_scope(self._factory) as session:
            product = session.get(Product, case.product_id)
            if product is None:
                raise KeyError(f"Product {case.product_id} not found")
        return DetailBundle(
            case=case,
            product=product,
            fields=[
                {"field": field, "observations": self._repo.observations(field.id)}
                for field in self._repo.fields(case_id)
            ],
            actions=self._repo.actions(case_id),
        )

    def wix_creation_price(self, product_id: uuid.UUID) -> str | None:
        """Return the current retail gross price required by Wix Catalog v3."""
        variant = self._products.get_default_variant(product_id)
        price_list = self._products.get_price_list_by_code("RETAIL_EUR")
        if variant is None or price_list is None:
            return None
        current = next(
            (
                price
                for price in self._products.list_prices(variant.id)
                if price.price_list_id == price_list.id and price.valid_until is None
            ),
            None,
        )
        return str(current.gross_amount) if current is not None and current.gross_amount is not None else None

    def decide(
        self,
        case_id: uuid.UUID,
        *,
        expected_row_version: int,
        resolution_type: str,
        selected_source: str | None = None,
        custom_value: object = None,
        note: str | None = None,
    ) -> ConflictCase:
        allowed = {
            "USE_HUB",
            "USE_WIX",
            "USE_SEVDESK",
            "USE_AMAZON",
            "CUSTOM_VALUE",
            "INTENTIONAL_DIFFERENCE",
            "IGNORE",
        }
        if resolution_type not in allowed:
            raise ValueError(f"Unsupported resolution_type {resolution_type}")
        field = self._repo.fields(case_id)[0]
        observations = self._repo.observations(field.id)
        source = selected_source or (
            {
                "USE_HUB": "hub",
                "USE_WIX": "wix",
                "USE_SEVDESK": "sevdesk",
                "USE_AMAZON": "amazon",
            }.get(resolution_type)
        )
        if resolution_type == "CUSTOM_VALUE":
            selected = custom_value
        elif source is not None:
            matches = [row for row in observations if row.source == source]
            if not matches:
                raise ValueError(f"No {source} observation exists for this case")
            selected = matches[-1].raw_value
        else:
            selected = None
        if resolution_type not in _TERMINAL_INTENTIONAL:
            selected = _coerce_selected_value(field.field_path, selected)
        case = self._repo.save_decision(
            case_id,
            expected_row_version=expected_row_version,
            resolution_type=resolution_type,
            selected_source=source,
            selected_value=selected,
            note=note,
        )
        if resolution_type in _TERMINAL_INTENTIONAL:
            case = self._repo.transition(
                case_id,
                expected_row_version=case.row_version,
                status="RESOLVED" if resolution_type == "INTENTIONAL_DIFFERENCE" else "IGNORED",
                resolution_type=resolution_type,
            )
        return case

    def remap_wix_mapping(
        self,
        case_id: uuid.UUID,
        *,
        expected_row_version: int,
        external_id: str,
        variant_external_id: str | None = None,
        note: str | None = None,
        actor: str = "conflict-wizard",
    ) -> ConflictCase:
        """Replace one broken Wix mapping after an explicit human selection.

        This is intentionally narrower than a generic edit: only mapping conflicts
        may use it, and the caller must have verified the candidate through Wix first.
        The old scanner conflict is closed so the next scan starts from the new ID.
        """
        selected_id = canonical_wix_id(external_id)
        if not selected_id:
            raise ValueError("Wix-Produkt-ID fehlt oder enthält mehrere IDs")
        selected_variant_id = canonical_wix_id(variant_external_id)
        if variant_external_id and not selected_variant_id:
            raise ValueError("Wix-Varianten-ID fehlt oder enthält mehrere IDs")
        with session_scope(self._factory) as session:
            case = session.get(ConflictCase, case_id)
            if case is None:
                raise KeyError(f"Conflict case {case_id} not found")
            if case.row_version != expected_row_version:
                raise ConflictOptimisticLockError(
                    f"Expected case row_version {expected_row_version}, found {case.row_version}"
                )
            if case.conflict_type != "WRONG_PRODUCT_MAPPING":
                raise ValueError("Nur Wix-Mapping-Konflikte koennen neu verknuepft werden")
            product = session.get(Product, case.product_id)
            if product is None:
                raise KeyError("Hub-Produkt fuer dieses Mapping nicht gefunden")
            mapping = session.scalar(
                select(ChannelMapping).where(
                    ChannelMapping.channel == "wix",
                    ChannelMapping.entity_type == "product",
                    ChannelMapping.internal_entity_id == case.product_id,
                )
            )
            created_mapping = mapping is None
            if mapping is None:
                mapping = ChannelMapping(
                    id=uuid.uuid4(),
                    channel="wix",
                    entity_type="product",
                    internal_entity_id=case.product_id,
                    external_id=f"pending:{uuid.uuid4()}",
                    sync_status="never",
                )
                session.add(mapping)
            target_variant: ProductVariant | None = None
            if selected_variant_id:
                target_variant = next(
                    (
                        row
                        for row in session.scalars(
                            select(ProductVariant)
                            .where(ProductVariant.product_id == case.product_id)
                            .order_by(ProductVariant.is_default.desc(), ProductVariant.sku)
                        ).all()
                        if row.sku.casefold() == product.sku.casefold()
                    ),
                    None,
                )
                if target_variant is None:
                    raise ValueError("Zur Hub-SKU wurde keine passende Hub-Variante gefunden")
            duplicate = next(
                (
                    row
                    for row in session.scalars(
                        select(ChannelMapping).where(
                            ChannelMapping.channel == "wix",
                            ChannelMapping.id != mapping.id,
                        )
                    ).all()
                    if canonical_wix_id(row.external_id)
                    == (selected_variant_id or selected_id)
                ),
                None,
            )
            if duplicate is not None:
                raise ValueError(
                    "Diese Wix-ID ist bereits einem anderen Hub-Produkt oder einer Variante zugeordnet"
                )
            before_data = (
                None
                if created_mapping
                else {
                    "entity_type": mapping.entity_type,
                    "internal_entity_id": str(mapping.internal_entity_id),
                    "external_id": mapping.external_id,
                    "external_parent_id": mapping.external_parent_id,
                }
            )
            mapping.external_id = selected_variant_id or selected_id
            mapping.external_parent_id = selected_id if selected_variant_id else None
            if target_variant is not None:
                mapping.entity_type = "variant"
                mapping.internal_entity_id = target_variant.id
            mapping.sync_status = "never"
            mapping.external_revision = None
            mapping.last_pulled_at = None
            mapping.last_external_updated_at = None
            mapping.last_success_at = None
            mapping.source_payload_hash = None
            mapping.last_error = None
            if case.origin_sync_conflict_id is not None:
                low = session.get(SyncConflict, case.origin_sync_conflict_id)
                if low is not None and low.resolved_at is None:
                    low.resolution = "mapping_reassigned"
                    low.resolved_by = actor
                    low.resolved_at = _now()
            session.add(
                AuditLog(
                    id=uuid.uuid4(),
                    actor_type="user",
                    actor_id=actor,
                    source="conflict_wizard",
                    action="conflict.remap_wix",
                    entity_type="variant" if target_variant is not None else "product",
                    entity_id=target_variant.id if target_variant is not None else case.product_id,
                    changed_fields=[
                        "wix_mapping.external_id",
                        "wix_mapping.external_parent_id",
                        "wix_mapping.entity_type",
                    ],
                    before_data=before_data,
                    after_data={
                        "entity_type": mapping.entity_type,
                        "internal_entity_id": str(mapping.internal_entity_id),
                        "external_id": mapping.external_id,
                        "external_parent_id": mapping.external_parent_id,
                        "note": note or "",
                    },
                    correlation_id=case.id,
                )
            )
            case.resolution_type = "REMAP_WIX"
            case.resolution_note = note
            case.status = "RESOLVED"
            case.resolved_at = _now()
            case.row_version += 1
            session.flush()
            return case

    def map_new_wix_product(
        self,
        case_id: uuid.UUID,
        *,
        expected_row_version: int,
        external_id: str,
        actor: str = "conflict-wizard",
    ) -> ConflictCase:
        """Attach a Wix product just created for this mapping conflict."""
        selected_id = canonical_wix_id(external_id)
        if not selected_id:
            raise ValueError("Wix-Produkt-ID fehlt oder enthält mehrere IDs")
        with session_scope(self._factory) as session:
            case = session.get(ConflictCase, case_id)
            if case is None:
                raise KeyError(f"Conflict case {case_id} not found")
            if case.row_version != expected_row_version:
                raise ConflictOptimisticLockError(
                    f"Expected case row_version {expected_row_version}, found {case.row_version}"
                )
            if case.conflict_type != "WRONG_PRODUCT_MAPPING":
                raise ValueError("Nur Wix-Mapping-Konflikte koennen ein Wix-Produkt anlegen")
            mapping = session.scalar(
                select(ChannelMapping).where(
                    ChannelMapping.channel == "wix",
                    ChannelMapping.entity_type == "product",
                    ChannelMapping.internal_entity_id == case.product_id,
                )
            )
            created_mapping = mapping is None
            if mapping is None:
                mapping = ChannelMapping(
                    id=uuid.uuid4(),
                    channel="wix",
                    entity_type="product",
                    internal_entity_id=case.product_id,
                    external_id=f"pending:{uuid.uuid4()}",
                    sync_status="never",
                )
                session.add(mapping)
            duplicate = next(
                (
                    row
                    for row in session.scalars(
                        select(ChannelMapping).where(
                            ChannelMapping.channel == "wix",
                            ChannelMapping.id != mapping.id,
                        )
                    ).all()
                    if canonical_wix_id(row.external_id) == selected_id
                ),
                None,
            )
            if duplicate is not None:
                raise ValueError(
                    "Diese Wix-ID ist bereits einem anderen Hub-Produkt oder einer Variante zugeordnet"
                )
            previous_id = None if created_mapping else mapping.external_id
            mapping.external_id = selected_id
            mapping.sync_status = "never"
            mapping.external_revision = None
            mapping.last_pulled_at = None
            mapping.last_external_updated_at = None
            mapping.last_success_at = None
            mapping.source_payload_hash = None
            mapping.last_error = None
            if case.origin_sync_conflict_id is not None:
                low = session.get(SyncConflict, case.origin_sync_conflict_id)
                if low is not None and low.resolved_at is None:
                    low.resolution = "wix_product_created"
                    low.resolved_by = actor
                    low.resolved_at = _now()
            session.add(
                AuditLog(
                    id=uuid.uuid4(), actor_type="user", actor_id=actor, source="conflict_wizard",
                    action="conflict.create_wix_product", entity_type="product", entity_id=case.product_id,
                    changed_fields=["wix_mapping.external_id"], before_data={"external_id": previous_id} if previous_id else None,
                    after_data={"external_id": selected_id}, correlation_id=case.id,
                )
            )
            case.resolution_type = "CREATE_WIX_PRODUCT"
            case.status = "RESOLVED"
            case.resolved_at = _now()
            case.row_version += 1
            session.flush()
            return case

    def archive_hub_product(
        self,
        case_id: uuid.UUID,
        *,
        expected_row_version: int,
        actor: str = "conflict-wizard",
    ) -> ConflictCase:
        """Archive the Hub product and close the current conflict safely."""
        with session_scope(self._factory) as session:
            case = session.get(ConflictCase, case_id)
            if case is None:
                raise KeyError(f"Conflict case {case_id} not found")
            if case.row_version != expected_row_version:
                raise ConflictOptimisticLockError(
                    f"Expected case row_version {expected_row_version}, found {case.row_version}"
                )
            product = session.get(Product, case.product_id)
            if product is None:
                raise KeyError(f"Product {case.product_id} not found")
            now = _now()
            product.active = False
            product.archived_at = now
            attributes = dict(product.attributes or {})
            attributes["wix_publish_eligible"] = False
            product.attributes = attributes
            product.row_version += 1
            if case.origin_sync_conflict_id is not None:
                low = session.get(SyncConflict, case.origin_sync_conflict_id)
                if low is not None and low.resolved_at is None:
                    low.resolution = "hub_product_archived"
                    low.resolved_by = actor
                    low.resolved_at = now
            session.add(
                AuditLog(
                    id=uuid.uuid4(), actor_type="user", actor_id=actor, source="conflict_wizard",
                    action="conflict.archive_hub_product", entity_type="product", entity_id=product.id,
                    changed_fields=["active", "archived_at", "attributes.wix_publish_eligible"],
                    before_data={"active": True, "wix_publish_eligible": True},
                    after_data={"active": False, "wix_publish_eligible": False}, correlation_id=case.id,
                )
            )
            case.resolution_type = "ARCHIVE_HUB_PRODUCT"
            case.status = "RESOLVED"
            case.resolved_at = now
            case.row_version += 1
            session.flush()
            return case

    def preview(
        self, case_id: uuid.UUID, *, channels: list[str] | None = None
    ) -> list[ConflictAction]:
        detail = self.detail(case_id)
        case = detail["case"]
        if case.resolution_type is None or case.resolution_type in _TERMINAL_INTENTIONAL:
            raise ValueError("The case has no actionable decision")
        field_bundle = detail["fields"][0]
        field = field_bundle["field"]
        observations = field_bundle["observations"]
        hub = next(
            (
                o.raw_value
                for o in reversed(observations)
                if isinstance(o, ConflictObservation) and o.source == "hub"
            ),
            None,
        )
        desired = field.selected_value
        selected_channels = set(
            channels
            or [
                o.source
                for o in observations
                if isinstance(o, ConflictObservation) and o.source != "hub"
            ]
        )
        actions: list[dict[str, Any]] = []
        hub_field = field.field_path
        if not equivalent(hub_field, hub, desired):
            supported = hub_field in _PRODUCT_FIELDS
            actions.append(
                {
                    "channel": "hub",
                    "action_type": "UPDATE_FIELD" if supported else "UNSUPPORTED",
                    "field_path": hub_field,
                    "before_value": hub,
                    "after_value": desired,
                    "selected": supported,
                    "status": "PLANNED" if supported else "SKIPPED",
                    "error": None
                    if supported
                    else "Dieses Hub-Feld hat noch keinen sicheren Schreibadapter.",
                }
            )
        for observation in observations:
            if (
                not isinstance(observation, ConflictObservation)
                or observation.source == "hub"
                or observation.source not in selected_channels
                or equivalent(hub_field, observation.raw_value, desired)
            ):
                continue
            supported = observation.source == "wix" and case.origin_sync_conflict_id is not None
            actions.append(
                {
                    "channel": observation.source,
                    "action_type": "SYNC_FIELD" if supported else "UNSUPPORTED",
                    "field_path": hub_field,
                    "before_value": observation.raw_value,
                    "after_value": desired,
                    "selected": supported,
                    "status": "PLANNED" if supported else "SKIPPED",
                    "error": None
                    if supported
                    else f"Für {observation.source} ist kein verifizierter Write-/Readback-Adapter vorhanden.",
                }
            )
        return self._repo.replace_plan(case_id, actions)

    def apply(
        self,
        case_id: uuid.UUID,
        *,
        expected_row_version: int,
        channel_apply_enabled: bool,
        actor: str = "conflict-wizard",
    ) -> ConflictCase:
        with session_scope(self._factory) as session:
            case = session.get(ConflictCase, case_id)
            if case is None:
                raise KeyError(f"Conflict case {case_id} not found")
            if case.row_version != expected_row_version:
                raise ConflictOptimisticLockError("Conflict case changed after preview")
            product = session.get(Product, case.product_id)
            if product is None:
                raise KeyError(f"Product {case.product_id} not found")
            if product.row_version != case.hub_row_version:
                raise StaleConflictError(
                    "Product changed after the conflict snapshot; refresh and decide again"
                )
            actions = list(
                session.scalars(
                    select(ConflictAction).where(
                        ConflictAction.conflict_case_id == case_id,
                        ConflictAction.status == "PLANNED",
                        ConflictAction.selected.is_(True),
                    )
                ).all()
            )
            if not actions:
                raise ValueError("No selected dry-run actions exist")
            queued = False
            for action in actions:
                action.attempted_at = _now()
                if action.channel == "hub":
                    if action.field_path not in _PRODUCT_FIELDS:
                        raise UnsupportedConflictAction(str(action.field_path))
                    before = getattr(product, str(action.field_path))
                    setattr(product, str(action.field_path), action.after_value)
                    product.row_version += 1
                    case.hub_row_version = product.row_version
                    action.status = "VERIFIED"
                    action.verified_at = _now()
                    session.add(
                        AuditLog(
                            id=uuid.uuid4(),
                            actor_type="user",
                            actor_id=actor,
                            source="conflict_wizard",
                            action="conflict.apply_hub",
                            entity_type="product",
                            entity_id=product.id,
                            changed_fields=[str(action.field_path)],
                            before_data={str(action.field_path): before},
                            after_data={str(action.field_path): action.after_value},
                            correlation_id=case.id,
                        )
                    )
                elif action.channel == "wix":
                    if not channel_apply_enabled:
                        raise UnsupportedConflictAction("Channel apply is disabled")
                    event = append_outbox_event(
                        session,
                        aggregate_type="product",
                        aggregate_id=product.id,
                        event_type="conflict.wix_apply",
                        payload={
                            "case_id": str(case.id),
                            "action_id": str(action.id),
                            "sync_conflict_id": str(case.origin_sync_conflict_id),
                        },
                    )
                    action.outbox_event_id = event.id
                    action.status = "QUEUED"
                    queued = True
                else:
                    raise UnsupportedConflictAction(f"Channel {action.channel} is not supported")
            case.status = "PARTIALLY_RESOLVED" if queued else "RESOLVED"
            case.resolved_at = None if queued else _now()
            case.row_version += 1
            session.flush()
            return case

    def finish_wix_action(self, event: OutboxEvent) -> None:
        action_id = uuid.UUID(str(event.payload["action_id"]))
        sync_id = uuid.UUID(str(event.payload["sync_conflict_id"]))
        with session_scope(self._factory) as session:
            action = session.get(ConflictAction, action_id)
            if action is None:
                return
            action.status = "VERIFIED"
            action.verified_at = _now()
            low = session.get(SyncConflict, sync_id)
            if low is not None and low.resolved_at is None:
                low.resolution = "keep_hub_and_push"
                low.resolved_by = "conflict-wizard"
                low.resolved_at = _now()
            case = session.get(ConflictCase, action.conflict_case_id)
            if case is not None:
                session.flush()
                pending = session.scalar(
                    select(ConflictAction.id)
                    .where(
                        ConflictAction.conflict_case_id == case.id,
                        ConflictAction.status.in_(("PLANNED", "QUEUED", "RUNNING", "FAILED")),
                    )
                    .limit(1)
                )
                if pending is None:
                    case.status = "RESOLVED"
                    case.resolved_at = _now()
                    case.row_version += 1

    def fail_wix_action(self, event: OutboxEvent, error: str) -> None:
        """Mirror worker failure into the durable case without closing it."""
        action_id = uuid.UUID(str(event.payload["action_id"]))
        with session_scope(self._factory) as session:
            action = session.get(ConflictAction, action_id)
            if action is None:
                return
            action.status = "FAILED"
            action.error = error[:4000]
            case = session.get(ConflictCase, action.conflict_case_id)
            if case is not None:
                case.status = "PARTIALLY_RESOLVED"
                case.resolved_at = None
                case.row_version += 1


def _resolve_owner(
    session: Session, low: SyncConflict
) -> tuple[Product | None, ProductVariant | None]:
    if low.entity_type == "product":
        return session.get(Product, low.internal_entity_id), None
    variant = session.get(ProductVariant, low.internal_entity_id)
    return (
        (session.get(Product, variant.product_id), variant) if variant is not None else (None, None)
    )


def _not_relevant(product: Product, low: SyncConflict, products: ProductHubRepository) -> bool:
    if product.archived_at is not None:
        return True
    if low.field_name in {"mapping", "channel_mapping"} and low.channel == "wix":
        publishable = product.attributes.get("wix_publish_eligible")
        return publishable is False or str(publishable).casefold() == "false"
    if low.field_name == "sku" and isinstance(low.external_value, str):
        resolved = products.resolve_sku(low.external_value)
        return resolved is not None and resolved.product.id == product.id
    return False


def _revision(low: SyncConflict) -> str | None:
    return low.external_updated_at.isoformat() if low.external_updated_at else None


def _coerce_selected_value(field_path: str, value: object) -> object:
    """Convert a user/source value to the Hub column's real type before planning."""
    if field_path != "active":
        return value
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "1", "yes", "ja", "on"}:
        return True
    if normalized in {"false", "0", "no", "nein", "off"}:
        return False
    raise ValueError("Aktiv/Sichtbar erwartet Ja oder Nein")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _conflict_summary(field_name: str, channel: str, external_value: object) -> str:
    """Create a useful queue summary without exposing raw JSON implementation details."""
    if field_name in {"mapping", "channel_mapping"} and channel == "wix":
        state = ""
        if isinstance(external_value, dict):
            state = str(external_value.get("state") or "").strip()
        messages = {
            "not_found": "Wix-Produkt unter der gespeicherten ID nicht gefunden; mögliche Ersatz-ID suchen.",
            "permission_denied": "Wix-Zugriff verweigert; zuerst Berechtigung prüfen.",
            "temporary_error": "Wix vorübergehend nicht erreichbar; später erneut prüfen.",
            "configuration_error": "Wix-Zugangsdaten fehlen; Dienstkonfiguration prüfen.",
            "invalid_mapping": "Gespeicherte Wix-ID ist ungültig; Mapping korrigieren.",
            "unmapped": "Für dieses Hub-Produkt besteht noch keine Wix-Verknüpfung.",
            "invalid_response": "Wix-Antwort ist unlesbar; Verbindung und Produkt prüfen.",
        }
        return messages.get(state, "Wix-Verknüpfung konnte nicht bestätigt werden; Details prüfen.")
    return f"{channel}: Product Hub und Channel enthalten unterschiedliche Werte."
