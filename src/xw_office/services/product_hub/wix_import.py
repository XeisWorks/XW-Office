"""Wix -> Product Hub staging importer (PR03).

Reads Wix products, variants, inventory and media via the existing Wix clients and
writes everything into staging tables (``models/product_hub_import.py``) for later
review/matching. **Never writes to Wix** and never touches a canonical product-hub
table directly — committing staged rows is a separate, explicit step (PR06).

Media rule: product images are preserved as product images (first = cover, subsequent
= gallery). Non-image media can still be reviewed as sample-score candidates in staging.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from xw_office.repositories.product_hub_import import ProductHubImportRepository
from xw_office.services.wix.client import WixProduct

logger = logging.getLogger(__name__)


class WixProductsSource(Protocol):
    """Structural interface satisfied by :class:`~xw_office.services.wix.client.WixProductsClient`."""

    def list_products(self, *, include_hidden: bool = True) -> list[WixProduct]: ...


class WixDetailsSource(Protocol):
    """Structural interface satisfied by
    :class:`~xw_office.services.wix.product_details_client.WixProductDetailsClient`."""

    def get_product_raw(self, product_id: str) -> dict[str, Any] | None: ...

    def query_variants(self, product_id: str) -> list[dict[str, Any]]: ...

    def query_inventory(self, product_id: str) -> list[dict[str, Any]]: ...


@dataclass
class WixImportReport:
    """Outcome of one :meth:`WixProductImporter.run` call."""

    batch_id: uuid.UUID
    products_seen: int = 0
    products_staged: int = 0
    variants_staged: int = 0
    assets_staged: int = 0
    inventory_rows_staged: int = 0
    categories_staged: int = 0
    errors: list[str] = field(default_factory=list)


class WixProductImporter:
    """Read-only Wix -> staging importer. Never calls a Wix write endpoint."""

    def __init__(
        self,
        *,
        products_client: WixProductsSource,
        details_client: WixDetailsSource,
        import_repo: ProductHubImportRepository,
    ) -> None:
        self._products_client = products_client
        self._details_client = details_client
        self._import_repo = import_repo

    def run(self) -> WixImportReport:
        """Import every Wix product into a fresh staging batch."""
        batch = self._import_repo.create_batch(source="wix")
        report = WixImportReport(batch_id=batch.id)

        products = self._products_client.list_products()
        report.products_seen = len(products)

        for product in products:
            product_id = str(product.id or "").strip()
            if not product_id:
                continue
            try:
                counts = self._import_one_product(batch.id, product_id)
            except Exception as exc:  # noqa: BLE001 - one bad product must not abort the batch
                logger.exception("Wix import: product %s failed", product_id)
                report.errors.append(f"{product_id}: {exc}")
                continue
            report.products_staged += 1
            report.variants_staged += counts["variants"]
            report.assets_staged += counts["assets"]
            report.inventory_rows_staged += counts["inventory"]
            report.categories_staged += counts["categories"]

        self._import_repo.finish_batch(
            batch.id,
            status="completed" if not report.errors else "failed",
            error_summary="; ".join(report.errors[:20]),
        )
        return report

    # -- per-product ------------------------------------------------------------

    def _import_one_product(self, batch_id: uuid.UUID, product_id: str) -> dict[str, int]:
        raw_product = self._details_client.get_product_raw(product_id)
        if raw_product is None:
            raise RuntimeError("product detail fetch returned nothing")
        raw_variants = self._details_client.query_variants(product_id)
        raw_inventory = self._details_client.query_inventory(product_id)

        sku, name = _default_sku_and_name(raw_product, raw_variants)
        revision = str(raw_product.get("revision") or raw_product.get("_revision") or "")

        staging_product = self._import_repo.ingest_staging_product(
            import_batch_id=batch_id,
            source="wix",
            source_key=product_id,
            source_external_id=product_id,
            sku=sku,
            name=name,
            raw_payload={
                "product": raw_product,
                "variants": raw_variants,
                "inventory": raw_inventory,
            },
            normalized_fields={"revision": revision, "visible": bool(raw_product.get("visible", True))},
        )

        assets_count = self._stage_media(staging_product.id, raw_product)
        variants_count = self._stage_variants(staging_product.id, raw_variants)
        inventory_count = self._stage_inventory(staging_product.id, raw_inventory)
        categories_count = self._stage_categories(staging_product.id, raw_product)

        return {
            "variants": variants_count,
            "assets": assets_count,
            "inventory": inventory_count,
            "categories": categories_count,
        }

    def _stage_media(self, staging_product_id: uuid.UUID, raw_product: dict[str, Any]) -> int:
        media_items = _extract_media_items(raw_product)
        image_index = 0
        for index, item in enumerate(media_items):
            is_image = _is_image_item(item)
            role = "COVER" if is_image and image_index == 0 else (
                "GALLERY_IMAGE" if is_image else "SAMPLE_SCORE"
            )
            self._import_repo.add_asset(
                staging_product_id,
                role=role,
                source_external_id=str(item.get("id") or "").strip(),
                source_url=_media_url(item),
                sort_order=index,
            )
            if is_image:
                image_index += 1
        return len(media_items)

    def _stage_variants(
        self, staging_product_id: uuid.UUID, raw_variants: list[dict[str, Any]]
    ) -> int:
        for variant in raw_variants:
            sku = str(variant.get("sku") or "").strip()
            choices = variant.get("choices") if isinstance(variant.get("choices"), dict) else {}
            name = ", ".join(f"{key}: {value}" for key, value in choices.items()) if choices else sku
            self._import_repo.add_variant(
                staging_product_id,
                sku=sku,
                name=name,
                source_external_id=str(
                    variant.get("id") or variant.get("variantId") or ""
                ).strip(),
                option_values=choices,
                raw_payload=variant,
            )
        return len(raw_variants)

    def _stage_inventory(
        self, staging_product_id: uuid.UUID, raw_inventory: list[dict[str, Any]]
    ) -> int:
        for item in raw_inventory:
            in_stock = item.get("inStock")
            self._import_repo.add_inventory(
                staging_product_id,
                quantity=_inventory_quantity(item),
                location_external_id=_inventory_location_id(item),
                stock_enabled=bool(in_stock) if isinstance(in_stock, bool) else True,
            )
        return len(raw_inventory)

    def _stage_categories(self, staging_product_id: uuid.UUID, raw_product: dict[str, Any]) -> int:
        categories = _extract_categories(raw_product)
        for category_id, category_name in categories:
            self._import_repo.add_category(
                staging_product_id,
                external_category_id=category_id,
                external_category_name=category_name,
            )
        return len(categories)


# ---------------------------------------------------------------------------
# Raw-payload parsing helpers (defensive: Wix's exact JSON shape varies by account/version,
# matching the existing style in services/wix/client.py and product_details_client.py)
# ---------------------------------------------------------------------------


def _extract_media_items(raw_product: dict[str, Any]) -> list[dict[str, Any]]:
    media = raw_product.get("media")
    if not isinstance(media, dict):
        return []
    for key in ("items", "item"):
        candidate = media.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    items_info = media.get("itemsInfo")
    if isinstance(items_info, dict):
        candidate = items_info.get("items")
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    main = media.get("main")
    if isinstance(main, dict):
        return [main]
    return []


def _media_url(item: dict[str, Any]) -> str:
    image = item.get("image")
    if isinstance(image, dict):
        url = str(image.get("url") or "").strip()
        if url:
            return url
    return str(item.get("url") or "").strip()


def _is_image_item(item: dict[str, Any]) -> bool:
    if isinstance(item.get("image"), dict):
        return True
    return str(item.get("mediaType") or item.get("type") or "").strip().lower() in {
        "image",
        "photo",
    }


def _default_sku_and_name(
    raw_product: dict[str, Any], raw_variants: list[dict[str, Any]]
) -> tuple[str, str]:
    name = str(raw_product.get("name") or "").strip()
    sku = ""
    if raw_variants:
        sku = str(raw_variants[0].get("sku") or "").strip()
    if not sku:
        inline_variants = raw_product.get("variants")
        if not isinstance(inline_variants, list):
            variants_info = raw_product.get("variantsInfo")
            inline_variants = variants_info.get("variants") if isinstance(variants_info, dict) else None
        if isinstance(inline_variants, list) and inline_variants and isinstance(inline_variants[0], dict):
            sku = str(inline_variants[0].get("sku") or "").strip()
    if not sku:
        sku = str(raw_product.get("sku") or "").strip()
    return sku, name


def _inventory_quantity(item: dict[str, Any]) -> int:
    for key in ("quantity", "availableQuantity", "totalQuantity"):
        value = item.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def _inventory_location_id(item: dict[str, Any]) -> str:
    location = item.get("locationId") or item.get("location")
    if isinstance(location, dict):
        return str(location.get("id") or "").strip()
    return str(location or "").strip()


def _extract_categories(raw_product: dict[str, Any]) -> list[tuple[str, str]]:
    raw_categories = (
        raw_product.get("categories")
        or raw_product.get("categoryIds")
        or raw_product.get("collectionIds")
        or []
    )
    results: list[tuple[str, str]] = []
    if not isinstance(raw_categories, list):
        return results
    for category in raw_categories:
        if isinstance(category, str) and category.strip():
            results.append((category.strip(), ""))
        elif isinstance(category, dict):
            category_id = str(category.get("id") or category.get("categoryId") or "").strip()
            category_name = str(
                category.get("name") or category.get("displayName") or category.get("label") or ""
            ).strip()
            if category_id:
                results.append((category_id, category_name))
    return results
