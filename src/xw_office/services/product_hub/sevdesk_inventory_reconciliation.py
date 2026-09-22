"""Read-only sevDesk-to-Hub inventory reconciliation for the desktop Shadow phase."""
from __future__ import annotations

from dataclasses import dataclass
import uuid

from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.product_hub import ChannelMapping, Product, ProductVariant
from xw_office.repositories.product_hub import ProductFilter, ProductHubRepository
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.sevdesk.part_client import PartClient


@dataclass(frozen=True)
class SevdeskInventoryReconciliationItem:
    sku: str
    product_name: str
    sevdesk_part_id: str
    hub_on_hand: int | None
    sevdesk_on_hand: int | None
    state: str  # equal | drift | skipped | error
    detail: str


@dataclass(frozen=True)
class SevdeskInventoryReconciliationResult:
    items: list[SevdeskInventoryReconciliationItem]

    @property
    def compared(self) -> int:
        return sum(1 for item in self.items if item.state in {"equal", "drift"})

    @property
    def drifts(self) -> int:
        return sum(1 for item in self.items if item.state == "drift")

    @property
    def skipped(self) -> int:
        return sum(1 for item in self.items if item.state == "skipped")

    @property
    def errors(self) -> int:
        return sum(1 for item in self.items if item.state == "error")


class SevdeskInventoryReconciliationService:
    """Compare exact, unambiguous physical Hub variants against sevDesk Parts.

    This runner performs no channel stock writes. It only reads sevDesk and delegates
    comparison to ``InventoryV2Service``, which maintains the existing conflict queue.
    Products with multiple stock-enabled variants for one parent-level sevDesk part are
    explicitly skipped: assigning one aggregate Part stock to several variants would
    manufacture false drift.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        part_client: PartClient,
        *,
        shadow_enabled: bool,
    ) -> None:
        self._products = ProductHubRepository(session_factory)
        self._inventory = InventoryV2Service(session_factory, shadow_enabled=shadow_enabled)
        self._part_client = part_client
        self._shadow_enabled = shadow_enabled

    def run(self) -> SevdeskInventoryReconciliationResult:
        if not self._shadow_enabled:
            raise RuntimeError("Inventory Shadow Mode ist nicht aktiviert")
        products = self._products.list_products(ProductFilter(status="live", active=True))
        physical = [product for product in products if product.product_type == "physical"]
        variants = self._products.list_variants_for_products([product.id for product in physical])
        variant_mappings = self._sevdesk_mapping_by_entity(
            self._products.list_channel_mappings_for_entities(
                [variant.id for variant in variants], entity_type="variant"
            )
        )
        product_mappings = self._sevdesk_mapping_by_entity(
            self._products.list_channel_mappings_for_entities(
                [product.id for product in physical], entity_type="product"
            )
        )
        by_product: dict[uuid.UUID, list[ProductVariant]] = {}
        for variant in variants:
            if variant.active and variant.stock_enabled:
                by_product.setdefault(variant.product_id, []).append(variant)

        items: list[SevdeskInventoryReconciliationItem] = []
        for product in physical:
            eligible = by_product.get(product.id, [])
            parent_part_id = self._parent_part_id(product, product_mappings.get(product.id))
            for variant in eligible:
                variant_mapping = variant_mappings.get(variant.id)
                part_id = str(variant_mapping.external_id).strip() if variant_mapping else ""
                if not part_id and len(eligible) == 1:
                    part_id = parent_part_id
                if not part_id:
                    items.append(
                        SevdeskInventoryReconciliationItem(
                            sku=variant.sku,
                            product_name=product.name,
                            sevdesk_part_id="",
                            hub_on_hand=None,
                            sevdesk_on_hand=None,
                            state="skipped",
                            detail=(
                                "Mehrere Lager-Varianten: jeder Variante muss ein eigener "
                                "sevDesk-Part zugeordnet werden"
                                if len(eligible) > 1
                                else "Keine sevDesk-Part-Zuordnung fuer Variante"
                            ),
                        )
                    )
                    continue
                self._compare_variant(
                    items=items, product=product, variant=variant, part_id=part_id
                )
            if not eligible:
                items.append(
                    SevdeskInventoryReconciliationItem(
                        sku=product.sku,
                        product_name=product.name,
                        sevdesk_part_id=parent_part_id,
                        hub_on_hand=None,
                        sevdesk_on_hand=None,
                        state="skipped",
                        detail="Keine aktive Lager-Variante",
                    )
                )
        return SevdeskInventoryReconciliationResult(items=items)

    @staticmethod
    def _sevdesk_mapping_by_entity(
        mappings: list[ChannelMapping],
    ) -> dict[uuid.UUID, ChannelMapping]:
        return {
            mapping.internal_entity_id: mapping
            for mapping in mappings
            if mapping.channel == "sevdesk" and str(mapping.external_id or "").strip()
        }

    @staticmethod
    def _parent_part_id(product: Product, mapping: ChannelMapping | None) -> str:
        if mapping is not None and str(mapping.external_id or "").strip():
            return str(mapping.external_id).strip()
        return str(product.sevdesk_part_id or "").strip()

    def _compare_variant(
        self,
        *,
        items: list[SevdeskInventoryReconciliationItem],
        product: Product,
        variant: ProductVariant,
        part_id: str,
    ) -> None:
        hub_on_hand = self._inventory.variant_on_hand(variant.id)
        try:
            sevdesk_on_hand = int(self._part_client.get_part_stock(part_id, strict=True))
        except Exception as exc:  # noqa: BLE001 - continue with independent products
            items.append(
                SevdeskInventoryReconciliationItem(
                    sku=variant.sku,
                    product_name=product.name,
                    sevdesk_part_id=part_id,
                    hub_on_hand=hub_on_hand,
                    sevdesk_on_hand=None,
                    state="error",
                    detail=str(exc),
                )
            )
            return
        drift = self._inventory.reconcile_variant_stock(variant.id, sevdesk_on_hand=sevdesk_on_hand)
        items.append(
            SevdeskInventoryReconciliationItem(
                sku=variant.sku,
                product_name=product.name,
                sevdesk_part_id=part_id,
                hub_on_hand=hub_on_hand,
                sevdesk_on_hand=sevdesk_on_hand,
                state="drift" if drift else "equal",
                detail="Abweichung in der Sync-Queue erfasst" if drift else "Bestaende stimmen ueberein",
            )
        )
