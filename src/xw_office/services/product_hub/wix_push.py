"""Wix push + reconcile + conflict management (PR11).

``WixPushService.push_product`` always re-derives the product's current desired
state from the Hub DB rather than trusting an outbox event's payload — the event is
only a "product X may need re-syncing" signal (see ``wix_push_handler`` below), which
sidesteps any staleness/ordering concerns between when an event was written and when
it's eventually processed.

Drift detection compares Wix's *live* value for each pushed field against the most
recent :class:`~xw_office.models.product_hub_sync.ExternalPayloadArchive` snapshot
(the "last known good" state after our last successful push). If Wix's live value
differs from that snapshot AND doesn't already match what the Hub wants to write,
someone changed it in Wix directly since our last sync — that's drift: a
``sync_conflict`` row is created and the field is *not* overwritten (never silent).
If Wix's live value already equals the Hub's desired value, or matches the last
snapshot (unchanged externally), pushing proceeds normally.

Push is gated by ``push_enabled`` (a callable, checked on every call — mirrors PR09's
``product_hub_edit_enabled`` pattern): when disabled, ``push_product`` is a pure no-op
with no Wix HTTP calls at all, which is the correct behavior for the outbox worker to
just mark the event processed and move on.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.product_hub import ChannelMapping, Product
from xw_office.models.product_hub_sync import OutboxEvent
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.outbox_worker import OutboxHandler
from xw_office.services.wix.product_details_client import WixProductDetailsClient, WixProductDetail

#: Hub-owned fields this adapter pushes — "Hub ist Master für definierte Felder" per
#: the build plan; this tuple *is* that definition. Extending it (e.g. compareAtPrice,
#: ribbon) is additive whenever the next channel-field need comes up.
PUSHABLE_FIELDS = ("name", "description", "price", "visible")

_WIX_FIELD_NAMES = {
    "name": "name",
    "description": "description",
    "price": "price",
    "visible": "visible",
}

#: Wix-facing field name -> Hub's ``Product`` column name, for "accept_external"
#: conflict resolution. ``price`` isn't here — it goes through
#: :meth:`~xw_office.repositories.product_hub.ProductHubRepository.set_price`
#: (a new effective-dated row), not a plain column assignment.
_HUB_FIELD_FOR = {"name": "name", "description": "description", "visible": "active"}

RESOLUTIONS = ("keep_hub_and_push", "accept_external", "ignore_once")


@dataclass(frozen=True)
class FieldConflict:
    field: str
    hub_value: str
    external_value: str


@dataclass
class PushOutcome:
    """Result of one :meth:`WixPushService.push_product` call."""

    status: str  # pushed | skipped_disabled | skipped_not_mapped | no_changes | conflict | error
    pushed_fields: list[str] = field(default_factory=list)
    conflicts: list[FieldConflict] = field(default_factory=list)
    error: str | None = None


def _format_price(amount: Decimal | float | str | None) -> str | None:
    if amount is None:
        return None
    try:
        return f"{Decimal(str(amount)):.2f}"
    except InvalidOperation:
        return None


class WixPushService:
    """Push the Hub's current state for one product to Wix, with drift detection."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        wix_client: WixProductDetailsClient,
        push_enabled: Callable[[], bool],
    ) -> None:
        self._product_repo = ProductHubRepository(session_factory)
        self._sync_repo = SyncRepository(session_factory)
        self._wix = wix_client
        self._push_enabled = push_enabled

    def _hub_values(self, product: Product) -> dict[str, str]:
        values: dict[str, str] = {
            "name": product.name,
            "description": product.description or "",
            "visible": "true" if product.active else "false",
        }
        variant = self._product_repo.get_default_variant(product.id)
        if variant is not None:
            price_list = self._product_repo.get_price_list_by_code("RETAIL_EUR")
            if price_list is not None:
                current_price = next(
                    (
                        p
                        for p in self._product_repo.list_prices(variant.id)
                        if p.price_list_id == price_list.id and p.valid_until is None
                    ),
                    None,
                )
                if current_price is not None:
                    formatted = _format_price(current_price.gross_amount)
                    if formatted is not None:
                        values["price"] = formatted
        return values

    @staticmethod
    def _external_values(detail: WixProductDetail) -> dict[str, str]:
        values: dict[str, str] = {
            "name": detail.name,
            "description": detail.description,
            "visible": "true" if detail.visible else "false",
        }
        if detail.price is not None:
            formatted = _format_price(detail.price)
            if formatted is not None:
                values["price"] = formatted
        return values

    def push_product(self, product_id: uuid.UUID) -> PushOutcome:
        if not self._push_enabled():
            return PushOutcome(status="skipped_disabled")

        product = self._product_repo.get_product(product_id)
        if product is None:
            return PushOutcome(status="error", error=f"Product {product_id} not found")

        mapping = self._wix_mapping_for(product_id)
        if mapping is None:
            return PushOutcome(status="skipped_not_mapped")
        external_id = mapping.external_id

        hub_values = self._hub_values(product)
        wix_detail = self._wix.get_product(external_id)
        if wix_detail is None:
            return PushOutcome(status="error", error=f"Could not fetch Wix product {external_id}")
        external_live = self._external_values(wix_detail)

        baseline = self._sync_repo.get_latest_external_payload(
            channel="wix", entity_type="product", external_id=external_id
        )
        baseline_values = baseline.payload if baseline is not None else None

        to_push: dict[str, str] = {}
        conflicts: list[FieldConflict] = []
        for field_name in PUSHABLE_FIELDS:
            if field_name not in hub_values or field_name not in external_live:
                continue
            hub_v = hub_values[field_name]
            ext_v = external_live[field_name]
            if hub_v == ext_v:
                continue  # already in sync, idempotent no-op for this field
            if baseline_values is not None:
                baseline_v = baseline_values.get(field_name)
                if baseline_v is not None and ext_v != baseline_v:
                    conflicts.append(FieldConflict(field_name, hub_v, ext_v))
                    continue
            to_push[field_name] = hub_v

        for conflict in conflicts:
            self._sync_repo.create_sync_conflict(
                channel="wix",
                entity_type="product",
                internal_entity_id=product_id,
                field_name=conflict.field,
                hub_value=conflict.hub_value,
                external_value=conflict.external_value,
            )

        if not to_push:
            return PushOutcome(status="conflict" if conflicts else "no_changes", conflicts=conflicts)

        pushed_fields: list[str] = []
        errors: list[str] = []
        for field_name, value in to_push.items():
            ok, err, status_code = self._wix.patch_product_field_with_conflict_detection(
                external_id, field=_WIX_FIELD_NAMES[field_name], value=_coerce_for_wix(field_name, value)
            )
            if ok:
                pushed_fields.append(field_name)
            elif status_code == 409:
                conflicts.append(FieldConflict(field_name, value, external_live.get(field_name, "")))
                self._sync_repo.create_sync_conflict(
                    channel="wix",
                    entity_type="product",
                    internal_entity_id=product_id,
                    field_name=field_name,
                    hub_value=value,
                    external_value=external_live.get(field_name),
                )
            else:
                errors.append(f"{field_name}: {err}")

        if pushed_fields:
            snapshot = {**external_live, **{f: hub_values[f] for f in pushed_fields}}
            self._sync_repo.archive_external_payload(
                channel="wix",
                entity_type="product",
                external_id=external_id,
                payload=snapshot,
                payload_hash=hashlib.sha256(
                    json.dumps(snapshot, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            )

        if errors:
            return PushOutcome(
                status="error",
                pushed_fields=pushed_fields,
                conflicts=conflicts,
                error="; ".join(errors),
            )
        if pushed_fields:
            return PushOutcome(status="pushed", pushed_fields=pushed_fields, conflicts=conflicts)
        return PushOutcome(status="conflict", conflicts=conflicts)

    def _wix_mapping_for(self, product_id: uuid.UUID) -> ChannelMapping | None:
        return next(
            (
                m
                for m in self._product_repo.list_channel_mappings(
                    entity_type="product", internal_entity_id=product_id
                )
                if m.channel == "wix"
            ),
            None,
        )

    def _refresh_baseline_field(self, external_id: str, field_name: str, value: str) -> None:
        baseline = self._sync_repo.get_latest_external_payload(
            channel="wix", entity_type="product", external_id=external_id
        )
        snapshot: dict[str, object] = dict(baseline.payload) if baseline is not None else {}
        snapshot[field_name] = value
        self._sync_repo.archive_external_payload(
            channel="wix",
            entity_type="product",
            external_id=external_id,
            payload=snapshot,
            payload_hash=hashlib.sha256(
                json.dumps(snapshot, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        )

    def resolve_conflict(
        self, conflict_id: uuid.UUID, *, resolution: str, resolved_by: str = ""
    ) -> None:
        """Apply a human's decision on an open :class:`SyncConflict` — the build plan's
        ``keep_hub_and_push`` / ``accept_external`` / ``ignore_once`` actions."""
        if resolution not in RESOLUTIONS:
            raise ValueError(f"Unknown resolution: {resolution}")
        if resolution == "keep_hub_and_push" and not self._push_enabled():
            raise RuntimeError("Wix push is disabled — cannot force-push while disabled")
        conflict = self._sync_repo.get_sync_conflict(conflict_id)
        if conflict is None:
            raise KeyError(f"Sync conflict {conflict_id} not found")

        product_id = conflict.internal_entity_id
        field_name = conflict.field_name

        if resolution == "keep_hub_and_push":
            mapping = self._wix_mapping_for(product_id)
            if mapping is None:
                raise KeyError(f"Product {product_id} is no longer mapped to Wix")
            hub_value = str(conflict.hub_value)
            ok, err, _status = self._wix.patch_product_field_with_conflict_detection(
                mapping.external_id,
                field=_WIX_FIELD_NAMES[field_name],
                value=_coerce_for_wix(field_name, hub_value),
            )
            if not ok:
                raise RuntimeError(f"keep_hub_and_push failed: {err}")
            self._refresh_baseline_field(mapping.external_id, field_name, hub_value)

        elif resolution == "accept_external":
            external_value = conflict.external_value
            if external_value is not None:
                if field_name == "price":
                    variant = self._product_repo.get_default_variant(product_id)
                    price_list = self._product_repo.get_price_list_by_code("RETAIL_EUR")
                    if variant is not None and price_list is not None:
                        self._product_repo.set_price(
                            variant.id,
                            price_list_id=price_list.id,
                            gross_amount=Decimal(str(external_value)),
                        )
                else:
                    hub_field = _HUB_FIELD_FOR.get(field_name)
                    product = self._product_repo.get_product(product_id)
                    if hub_field is not None and product is not None:
                        value: object = (
                            str(external_value) == "true"
                            if hub_field == "active"
                            else external_value
                        )
                        self._product_repo.update_product(
                            product_id,
                            expected_row_version=product.row_version,
                            **{hub_field: value},
                        )
                mapping = self._wix_mapping_for(product_id)
                if mapping is not None:
                    self._refresh_baseline_field(mapping.external_id, field_name, str(external_value))

        # ignore_once: resolve the record without touching Hub or Wix state — the
        # divergence stays and will be re-detected on the next push attempt.

        self._sync_repo.resolve_sync_conflict(conflict_id, resolution=resolution, resolved_by=resolved_by)


def _coerce_for_wix(field_name: str, value: str) -> object:
    if field_name == "price":
        return float(value)
    if field_name == "visible":
        return value == "true"
    return value


def wix_push_handler(push_service: WixPushService, product_repo: ProductHubRepository) -> OutboxHandler:
    """Outbox handler for ``product.updated``/``price.changed`` events.

    Resolves the aggregate to a product id (events may carry either a product id or a
    variant id — see the mapping in ``editing.py``) and re-syncs it. ``error`` outcomes
    raise so :class:`~xw_office.services.product_hub.outbox_worker.OutboxWorker`
    applies its normal backoff/retry; every other outcome (pushed, no changes,
    conflict recorded, disabled, not yet mapped to Wix) is a legitimate terminal state
    for this event, not a failure to retry.
    """

    def handler(event: OutboxEvent) -> None:
        if event.aggregate_type == "product":
            product_id = event.aggregate_id
        elif event.aggregate_type == "product_variant":
            variant = product_repo.get_variant(event.aggregate_id)
            if variant is None:
                return
            product_id = variant.product_id
        else:
            return

        outcome = push_service.push_product(product_id)
        if outcome.status == "error":
            raise RuntimeError(outcome.error or "Wix push failed")

    return handler
