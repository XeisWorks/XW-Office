"""Project canonical Product-Hub stock to sevDesk and Wix safely.

The Product Hub is the only writer after inventory cutover.  This module keeps
provider writes deliberately small and defensive:

* exact variant mappings are preferred; product-level fallbacks are allowed only
  when a product has one active stock-enabled variant;
* the last projected quantity is archived and a direct external edit becomes a
  durable ``sync_conflict`` instead of being silently overwritten;
* dry-run is the default and provider writes require an explicit feature gate;
* Wix inventory writes use the current V3 revision and only send quantity.

No provider is contacted when the caller asks for a dry run with a missing
mapping or missing Hub stock row.  Those cases remain visible in the result and
are intentionally not converted into a fabricated zero quantity.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import uuid
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.product_hub import ChannelMapping, Product, ProductVariant
from xw_office.models.product_hub_inventory import InventoryStock
from xw_office.repositories.product_hub import ProductFilter, ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.wix.identifiers import canonical_wix_id

logger = logging.getLogger(__name__)

DEFAULT_LOCATION_CODE = "MAIN"
_CHANNEL_ENTITY_TYPE = "inventory_stock"


class SevdeskStockProvider(Protocol):
    def get_part_stock(self, part_id: str, *, strict: bool = False) -> int: ...

    def set_part_stock(self, part_id: str, new_stock: int) -> None: ...


class WixInventoryProvider(Protocol):
    def query_inventory(self, product_id: str) -> list[dict[str, Any]]: ...

    def update_inventory_item(
        self, inventory_item_id: str, *, revision: str, quantity: int, reason: str = "MANUAL"
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class InventoryProjectionItem:
    variant_id: uuid.UUID
    sku: str
    channel: str
    external_id: str
    desired_quantity: int | None
    external_quantity: int | None
    state: str  # equal | would_project | projected | conflict | skipped | disabled | error
    detail: str = ""


@dataclass
class InventoryProjectionResult:
    items: list[InventoryProjectionItem] = field(default_factory=list)

    @property
    def projected(self) -> int:
        return sum(item.state == "projected" for item in self.items)

    @property
    def would_project(self) -> int:
        return sum(item.state == "would_project" for item in self.items)

    @property
    def equal(self) -> int:
        return sum(item.state == "equal" for item in self.items)

    @property
    def conflicts(self) -> int:
        return sum(item.state == "conflict" for item in self.items)

    @property
    def skipped(self) -> int:
        return sum(item.state == "skipped" for item in self.items)

    @property
    def errors(self) -> int:
        return sum(item.state == "error" for item in self.items)

    @property
    def successful(self) -> bool:
        return not self.errors and not self.conflicts


@dataclass(frozen=True)
class _Target:
    variant: ProductVariant
    product: Product
    mapping: ChannelMapping
    external_id: str
    external_parent_id: str


class InventoryProjectionService:
    """Reconcile Hub quantities to both supported inventory channels."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        sevdesk: SevdeskStockProvider | None = None,
        wix: WixInventoryProvider | None = None,
        write_enabled: Callable[[], bool] | None = None,
        location_code: str = DEFAULT_LOCATION_CODE,
    ) -> None:
        self._products = ProductHubRepository(session_factory)
        self._inventory = InventoryRepository(session_factory)
        self._sync = SyncRepository(session_factory)
        self._sevdesk = sevdesk
        self._wix = wix
        self._write_enabled = write_enabled or (lambda: False)
        self._location_code = str(location_code or DEFAULT_LOCATION_CODE).strip()

    def run(
        self,
        *,
        dry_run: bool = True,
        variant_ids: Iterable[uuid.UUID] | None = None,
    ) -> InventoryProjectionResult:
        """Project all active physical variants, or a selected subset.

        ``dry_run=False`` is rejected unless the caller's explicit write gate is
        active.  This makes accidentally wiring the service into a worker safe.
        """
        if not dry_run and not self._write_enabled():
            return InventoryProjectionResult(
                [
                    InventoryProjectionItem(
                        variant_id=uuid.UUID(int=0),
                        sku="",
                        channel="*",
                        external_id="",
                        desired_quantity=None,
                        external_quantity=None,
                        state="disabled",
                        detail="Bestandsprojektionen sind durch den Write-Gate deaktiviert.",
                    )
                ]
            )

        location = self._inventory.get_location_by_code(self._location_code)
        if location is None:
            return InventoryProjectionResult(
                [
                    InventoryProjectionItem(
                        variant_id=uuid.UUID(int=0), sku="", channel="*", external_id="",
                        desired_quantity=None, external_quantity=None, state="skipped",
                        detail=f"Lagerort {self._location_code!r} ist nicht angelegt.",
                    )
                ]
            )

        products = self._products.list_products(ProductFilter(status="live", active=True))
        products = [product for product in products if product.product_type == "physical"]
        variants = self._products.list_variants_for_products([product.id for product in products])
        allowed = set(variant_ids or ())
        if allowed:
            variants = [variant for variant in variants if variant.id in allowed]
        variants = [variant for variant in variants if variant.active and variant.stock_enabled]
        products_by_id = {product.id: product for product in products}
        eligible_by_product: dict[uuid.UUID, list[ProductVariant]] = {}
        for variant in variants:
            eligible_by_product.setdefault(variant.product_id, []).append(variant)
        stock_by_variant = {
            stock.variant_id: stock
            for stock in self._inventory.list_stock_by_variants(
                [variant.id for variant in variants], location.id
            )
        }
        variant_mappings = self._variant_mappings(variants)
        product_mappings = self._mapping_by_product(products)

        result = InventoryProjectionResult()
        if self._sevdesk is not None:
            for target in self._sevdesk_targets(
                variants, products_by_id, eligible_by_product, variant_mappings, product_mappings
            ):
                result.items.append(
                    self._project_sevdesk(target, stock_by_variant.get(target.variant.id), dry_run=dry_run)
                )
        if self._wix is not None:
            for product in products:
                product_variants = eligible_by_product.get(product.id, [])
                if not product_variants:
                    continue
                result.items.extend(
                    self._project_wix_product(
                        product,
                        product_variants,
                        stock_by_variant,
                        variant_mappings,
                        product_mappings.get(("wix", product.id)),
                        location_id=str(location.id),
                        dry_run=dry_run,
                    )
                )
        return result

    def _mapping_by_product(self, products: list[Product]) -> dict[tuple[str, uuid.UUID], ChannelMapping]:
        ids = [product.id for product in products]
        rows = self._products.list_channel_mappings_for_entities(ids, entity_type="product")
        return {(row.channel, row.internal_entity_id): row for row in rows}

    def _variant_mappings(self, variants: list[ProductVariant]) -> dict[tuple[str, uuid.UUID], ChannelMapping]:
        rows = self._products.list_channel_mappings_for_entities(
            [variant.id for variant in variants], entity_type="variant"
        )
        return {(row.channel, row.internal_entity_id): row for row in rows}

    def _sevdesk_targets(
        self,
        variants: list[ProductVariant],
        products_by_id: dict[uuid.UUID, Product],
        eligible_by_product: dict[uuid.UUID, list[ProductVariant]],
        _unused_variant_mappings: dict[tuple[str, uuid.UUID], ChannelMapping],
        product_mappings: dict[tuple[str, uuid.UUID], ChannelMapping],
    ) -> list[_Target]:
        variant_mappings = self._variant_mappings(variants)
        targets: list[_Target] = []
        used: dict[str, uuid.UUID] = {}
        for variant in variants:
            product = products_by_id[variant.product_id]
            mapping = variant_mappings.get(("sevdesk", variant.id))
            if mapping is None and len(eligible_by_product.get(product.id, [])) == 1:
                mapping = product_mappings.get(("sevdesk", product.id))
            if mapping is None and len(eligible_by_product.get(product.id, [])) == 1:
                legacy_part_id = str(product.sevdesk_part_id or "").strip()
                if legacy_part_id:
                    mapping = ChannelMapping(
                        id=uuid.UUID(int=0), channel="sevdesk", entity_type="product",
                        internal_entity_id=product.id, external_id=legacy_part_id,
                    )
            external_id = str(mapping.external_id or "").strip() if mapping else ""
            if not external_id:
                continue
            owner = used.get(external_id)
            if owner is not None and owner != variant.id:
                logger.warning("Skipping duplicate sevDesk Part mapping %s", external_id)
                continue
            used[external_id] = variant.id
            targets.append(
                _Target(
                    variant=variant, product=product, mapping=mapping, external_id=external_id,
                    external_parent_id="",
                )
            )
        return targets

    def _project_sevdesk(
        self, target: _Target, stock: InventoryStock | None, *, dry_run: bool
    ) -> InventoryProjectionItem:
        if stock is None:
            return self._skipped(target, "Kein bestätigter Hub-Bestand für den Lagerort vorhanden.", "sevdesk")
        if self._sevdesk is None:
            return self._skipped(target, "sevDesk-Projektor ist nicht konfiguriert.", "sevdesk")
        desired = max(0, int(stock.on_hand))
        try:
            current = int(self._sevdesk.get_part_stock(target.external_id, strict=True))
            return self._reconcile_external(
                target, channel="sevdesk", current=current, desired=desired,
                revision=None, dry_run=dry_run,
                write=lambda: self._write_sevdesk(target.external_id, desired),
            )
        except Exception as exc:  # noqa: BLE001 - one channel item must not abort others
            return self._error(target, "sevdesk", str(exc))

    def _project_wix_product(
        self,
        product: Product,
        variants: list[ProductVariant],
        stock_by_variant: dict[uuid.UUID, InventoryStock],
        variant_mappings: dict[tuple[str, uuid.UUID], ChannelMapping],
        product_mapping: ChannelMapping | None,
        *,
        location_id: str,
        dry_run: bool,
    ) -> list[InventoryProjectionItem]:
        if self._wix is None:
            return [
                self._skipped(
                    _Target(variant=variant, product=product, mapping=product_mapping or self._empty_mapping(),
                            external_id="", external_parent_id=""),
                    "Wix-Projektor ist nicht konfiguriert.", "wix"
                ) for variant in variants
            ]
        parent_id = str(product_mapping.external_id or "").strip() if product_mapping else ""
        for variant in variants:
            mapping = variant_mappings.get(("wix", variant.id))
            if mapping is not None and mapping.external_parent_id:
                parent_id = str(mapping.external_parent_id).strip()
                break
        if not parent_id:
            return [
                self._skipped(
                    _Target(variant=variant, product=product, mapping=product_mapping or self._empty_mapping(),
                            external_id="", external_parent_id=""),
                    "Keine eindeutige Wix-Produktzuordnung.", "wix"
                ) for variant in variants
            ]
        items = self._wix.query_inventory(canonical_wix_id(parent_id))
        result: list[InventoryProjectionItem] = []
        for variant in variants:
            mapping = variant_mappings.get(("wix", variant.id)) or product_mapping
            target = _Target(
                variant=variant, product=product,
                mapping=mapping or self._empty_mapping(),
                external_id="", external_parent_id=parent_id,
            )
            if mapping is None:
                result.append(self._skipped(target, "Keine Wix-Varianten-Zuordnung.", "wix"))
                continue
            match = self._match_wix_inventory_item(
                items, mapping, product_id=parent_id, variant_count=len(variants)
            )
            if match is None:
                result.append(self._skipped(target, "Keine eindeutige Wix-Inventarposition.", "wix"))
                continue
            item_id = self._item_id(match)
            target = _Target(
                variant=variant, product=product, mapping=mapping,
                external_id=item_id, external_parent_id=parent_id,
            )
            if not item_id:
                result.append(self._skipped(target, "Wix-Inventarposition ohne ID.", "wix"))
                continue
            if match.get("trackQuantity") is False or "quantity" not in match:
                result.append(self._skipped(target, "Wix verwendet keine exakte Mengenführung.", "wix"))
                continue
            revision = str(match.get("revision") or match.get("_revision") or "").strip()
            if not revision:
                result.append(self._skipped(target, "Wix-Inventarposition ohne Revision.", "wix"))
                continue
            stock = stock_by_variant.get(variant.id)
            if stock is None:
                result.append(self._skipped(target, "Kein bestätigter Hub-Bestand für den Lagerort vorhanden.", "wix"))
                continue
            desired = max(0, int(stock.on_hand))
            try:
                current = int(match.get("quantity") or 0)
                result.append(
                    self._reconcile_external(
                        target, channel="wix", current=current, desired=desired,
                        revision=revision, dry_run=dry_run,
                        write=lambda item_id=item_id, revision=revision, desired=desired: self._write_wix(
                            item_id, revision, desired
                        ),
                        location_id=location_id,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                result.append(self._error(target, "wix", str(exc)))
        return result

    @staticmethod
    def _match_wix_inventory_item(
        items: list[dict[str, Any]], mapping: ChannelMapping, *, product_id: str, variant_count: int
    ) -> dict[str, Any] | None:
        external = str(mapping.external_id or "").strip()
        variant_id = canonical_wix_id(external)
        exact = [
            item for item in items
            if canonical_wix_id(str(item.get("variantId") or "")) == variant_id
            or str(item.get("id") or item.get("_id") or "").strip() == external
        ]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None
        if variant_count == 1:
            product_matches = [
                item for item in items
                if canonical_wix_id(str(item.get("productId") or "")) == canonical_wix_id(product_id)
            ]
            if len(product_matches) == 1:
                return product_matches[0]
            if len(items) == 1:
                return items[0]
        return None

    @staticmethod
    def _item_id(item: dict[str, Any]) -> str:
        return str(item.get("id") or item.get("_id") or "").strip()

    def _reconcile_external(
        self,
        target: _Target,
        *,
        channel: str,
        current: int,
        desired: int,
        revision: str | None,
        dry_run: bool,
        write: Callable[[], str | None],
        location_id: str = "",
    ) -> InventoryProjectionItem:
        baseline = self._sync.get_latest_external_payload(
            channel=channel, entity_type=_CHANNEL_ENTITY_TYPE, external_id=target.external_id
        )
        baseline_quantity = self._baseline_quantity(baseline.payload if baseline else None)
        if baseline_quantity is not None and current != baseline_quantity and current != desired:
            self._sync.upsert_scanned_conflict(
                channel=channel,
                entity_type=_CHANNEL_ENTITY_TYPE,
                internal_entity_id=target.variant.id,
                field_name="on_hand",
                hub_value=desired,
                external_value=current,
            )
            return InventoryProjectionItem(
                variant_id=target.variant.id, sku=target.variant.sku, channel=channel,
                external_id=target.external_id, desired_quantity=desired,
                external_quantity=current, state="conflict",
                detail="Externer Bestand wurde seit der letzten Projektion direkt geändert.",
            )
        if current == desired:
            self._archive_projection(target, channel, quantity=current, revision=revision, location_id=location_id)
            return InventoryProjectionItem(
                variant_id=target.variant.id, sku=target.variant.sku, channel=channel,
                external_id=target.external_id, desired_quantity=desired,
                external_quantity=current, state="equal", detail="Bestand ist bereits identisch.",
            )
        if dry_run:
            return InventoryProjectionItem(
                variant_id=target.variant.id, sku=target.variant.sku, channel=channel,
                external_id=target.external_id, desired_quantity=desired,
                external_quantity=current, state="would_project",
                detail="Dry-Run: keine externe Änderung ausgeführt.",
            )
        new_revision = write()
        if channel == "sevdesk":
            verified = int(self._sevdesk.get_part_stock(target.external_id, strict=True)) if self._sevdesk else desired
            if verified != desired:
                raise RuntimeError(f"sevDesk-Bestand nach Projektion ist {verified}, erwartet {desired}")
        elif channel == "wix" and new_revision is None:
            raise RuntimeError("Wix lieferte nach der Projektion keine neue Revision")
        self._archive_projection(target, channel, quantity=desired, revision=new_revision or revision, location_id=location_id)
        return InventoryProjectionItem(
            variant_id=target.variant.id, sku=target.variant.sku, channel=channel,
            external_id=target.external_id, desired_quantity=desired,
            external_quantity=current, state="projected", detail="Bestand erfolgreich projiziert.",
        )

    def _write_sevdesk(self, part_id: str, desired: int) -> str | None:
        assert self._sevdesk is not None
        self._sevdesk.set_part_stock(part_id, desired)
        return None

    def _write_wix(self, item_id: str, revision: str, desired: int) -> str | None:
        assert self._wix is not None
        result = self._wix.update_inventory_item(item_id, revision=revision, quantity=desired)
        return str(result.get("revision") or result.get("_revision") or "").strip() or None

    def _archive_projection(
        self,
        target: _Target,
        channel: str,
        *,
        quantity: int,
        revision: str | None,
        location_id: str,
    ) -> None:
        payload = {
            "quantity": int(quantity),
            "variant_id": str(target.variant.id),
            "sku": target.variant.sku,
            "location_id": location_id,
            "revision": revision or "",
            "source": "product_hub_inventory_projection",
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        self._sync.archive_external_payload_if_changed(
            channel=channel,
            entity_type=_CHANNEL_ENTITY_TYPE,
            external_id=target.external_id,
            payload=payload,
            payload_hash=digest,
        )
        if target.mapping.id.int != 0:
            self._products.record_channel_push(
                target.mapping.id, external_revision=revision, payload_hash=digest
            )
        self._sync.upsert_scanned_conflict(
            channel=channel,
            entity_type=_CHANNEL_ENTITY_TYPE,
            internal_entity_id=target.variant.id,
            field_name="on_hand",
            hub_value=int(quantity),
            external_value=int(quantity),
        )

    @staticmethod
    def _baseline_quantity(payload: dict[str, object] | None) -> int | None:
        if not isinstance(payload, dict) or "quantity" not in payload:
            return None
        try:
            return int(payload["quantity"])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _empty_mapping() -> ChannelMapping:
        return ChannelMapping(
            id=uuid.UUID(int=0), channel="", entity_type="", internal_entity_id=uuid.UUID(int=0), external_id=""
        )

    @staticmethod
    def _skipped(target: _Target, detail: str, channel: str) -> InventoryProjectionItem:
        return InventoryProjectionItem(
            variant_id=target.variant.id, sku=target.variant.sku, channel=channel,
            external_id=target.external_id, desired_quantity=None,
            external_quantity=None, state="skipped", detail=detail,
        )

    @staticmethod
    def _error(target: _Target, channel: str, detail: str) -> InventoryProjectionItem:
        return InventoryProjectionItem(
            variant_id=target.variant.id, sku=target.variant.sku, channel=channel,
            external_id=target.external_id, desired_quantity=None,
            external_quantity=None, state="error", detail=detail,
        )

