"""Repository layer for the XW Product Hub canonical schema (PR01).

Read/write access to ``product``, ``product_variant`` and the surrounding reference
tables (identifiers, assets, price lists...). This repository does not touch
``SettingKV["inventory.products"]`` / ``inventory.stock_levels`` — those stay owned by
``xw_office.services.inventory.service.InventoryService`` until PR16.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime
import re
import uuid
from collections.abc import Generator

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import (
    ChannelMapping,
    Product,
    ProductAsset,
    ProductIdentifier,
    ProductSkuAlias,
    ProductVariant,
)

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")


class OptimisticLockError(RuntimeError):
    """Raised by :meth:`ProductHubRepository.update_product` on a stale ``row_version``."""


def normalize_sku(raw_sku: str) -> str:
    """Canonical SKU comparison form: trim + uppercase.

    Per docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml ``constraints_global``: comparison
    uses trim+uppercase; this repository also stores SKUs in this normalized form, matching
    the existing convention in ``ProductCatalogService`` (``part.sku.strip().upper()``).
    """
    return str(raw_sku or "").strip().upper()


def slugify(value: str) -> str:
    """Return a URL-safe slug base (uniqueness is the caller's/repository's job)."""
    text = str(value or "").strip().lower()
    text = _SLUG_INVALID_CHARS.sub("-", text).strip("-")
    return text or "product"


@dataclass(frozen=True)
class ProductFilter:
    """Optional filters for :meth:`ProductHubRepository.list_products`."""

    status: str | None = None
    active: bool | None = None
    family_id: uuid.UUID | None = None
    search: str | None = None


@dataclass(frozen=True)
class ResolvedSku:
    """Result of :meth:`ProductHubRepository.resolve_sku`."""

    product: Product
    variant: ProductVariant
    #: "sku" when the variant's own SKU matched directly, "alias" when only a
    #: product_sku_alias row matched — the matching engine (PR05) uses this to tell
    #: match_method "exact_sku" apart from "sku_alias".
    matched_via: str = "sku"


class ProductHubRepository:
    """Data access for the canonical product/variant/pricing/asset schema."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    # -- products -------------------------------------------------------------

    def get_product(self, product_id: uuid.UUID) -> Product | None:
        with self._scope() as session:
            return session.get(Product, product_id)

    def get_product_by_sku(self, sku: str) -> Product | None:
        resolved = self.resolve_sku(sku)
        return resolved.product if resolved is not None else None

    def list_products(self, filters: ProductFilter | None = None) -> list[Product]:
        filters = filters or ProductFilter()
        with self._scope() as session:
            stmt = select(Product)
            if filters.status is not None:
                stmt = stmt.where(Product.status == filters.status)
            if filters.active is not None:
                stmt = stmt.where(Product.active == filters.active)
            if filters.family_id is not None:
                stmt = stmt.where(Product.family_id == filters.family_id)
            if filters.search:
                needle = f"%{filters.search.strip()}%"
                stmt = stmt.where(Product.name.ilike(needle))
            stmt = stmt.order_by(Product.name)
            return list(session.scalars(stmt).all())

    def create_product(
        self,
        *,
        sku: str,
        name: str,
        status: str = "draft",
        product_type: str = "physical",
        brand_name: str = "",
        category: str = "",
        short_description: str = "",
        description: str = "",
        min_stock_target: int = 5,
        reprint_batch_qty: int = 3,
        stock_enabled: bool = True,
    ) -> tuple[Product, ProductVariant]:
        """Create one canonical product with exactly one default variant.

        Implements the confirmed "safe migration rule": every known SKU is imported as
        its own product with a default variant first; curated grouping into parent
        products (e.g. MusikHeroes families) is a separate, explicit step (PR06+).
        """
        clean_sku = normalize_sku(sku)
        if not clean_sku:
            raise ValueError("sku is required")
        clean_name = str(name or "").strip() or clean_sku
        with self._scope() as session:
            product = Product(
                id=uuid.uuid4(),
                sku=clean_sku,
                name=clean_name,
                category=str(category or "").strip() or None,
                is_digital=not stock_enabled,
                min_stock_target=min_stock_target,
                reprint_batch_qty=reprint_batch_qty,
                status=status,
                brand_name=str(brand_name or "").strip() or None,
                slug=self._generate_unique_slug(session, clean_name or clean_sku),
                short_description=short_description or None,
                description=description or None,
                product_type=product_type,
                active=True,
                attributes={},
                row_version=1,
            )
            session.add(product)
            session.flush()

            variant = ProductVariant(
                id=uuid.uuid4(),
                product_id=product.id,
                sku=clean_sku,
                name=clean_name,
                is_default=True,
                active=True,
                stock_enabled=stock_enabled,
                option_values={},
                attributes={},
            )
            session.add(variant)
            session.flush()
            return product, variant

    def update_product(
        self,
        product_id: uuid.UUID,
        *,
        expected_row_version: int,
        **fields: object,
    ) -> Product:
        """Optimistic-locked partial update; raises :class:`OptimisticLockError` if stale."""
        with self._scope() as session:
            product = session.get(Product, product_id)
            if product is None:
                raise KeyError(f"Product {product_id} not found")
            if product.row_version != expected_row_version:
                raise OptimisticLockError(
                    f"Product {product_id} row_version is {product.row_version}, "
                    f"expected {expected_row_version}"
                )
            for field_name, value in fields.items():
                if not hasattr(product, field_name):
                    raise ValueError(f"Unknown product field: {field_name}")
                setattr(product, field_name, value)
            product.row_version += 1
            product.updated_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return product

    # -- SKU resolution ---------------------------------------------------------

    def resolve_sku(self, raw_sku: str) -> ResolvedSku | None:
        """Resolve any known SKU (variant SKU or legacy alias) to product + variant."""
        needle = normalize_sku(raw_sku)
        if not needle:
            return None
        with self._scope() as session:
            matched_via = "sku"
            variant = session.scalar(
                select(ProductVariant).where(func.upper(ProductVariant.sku) == needle)
            )
            if variant is None:
                matched_via = "alias"
                alias = session.scalar(
                    select(ProductSkuAlias).where(func.upper(ProductSkuAlias.alias_sku) == needle)
                )
                if alias is None:
                    return None
                if alias.variant_id is not None:
                    variant = session.get(ProductVariant, alias.variant_id)
                if variant is None:
                    variant = session.scalar(
                        select(ProductVariant).where(
                            ProductVariant.product_id == alias.product_id,
                            ProductVariant.is_default.is_(True),
                        )
                    )
                if variant is None:
                    return None
            product = session.get(Product, variant.product_id)
            if product is None:
                return None
            return ResolvedSku(product=product, variant=variant, matched_via=matched_via)

    # -- variants -----------------------------------------------------------

    def list_variants(self, product_id: uuid.UUID) -> list[ProductVariant]:
        with self._scope() as session:
            stmt = (
                select(ProductVariant)
                .where(ProductVariant.product_id == product_id)
                .order_by(ProductVariant.is_default.desc(), ProductVariant.sku)
            )
            return list(session.scalars(stmt).all())

    def get_variant(self, variant_id: uuid.UUID) -> ProductVariant | None:
        with self._scope() as session:
            return session.get(ProductVariant, variant_id)

    def get_default_variant(self, product_id: uuid.UUID) -> ProductVariant | None:
        with self._scope() as session:
            return session.scalar(
                select(ProductVariant).where(
                    ProductVariant.product_id == product_id,
                    ProductVariant.is_default.is_(True),
                )
            )

    def set_default_variant(self, variant_id: uuid.UUID) -> ProductVariant:
        """Make *variant_id* the sole default variant of its product (transactional).

        This is the DB-portable substitute for a PostgreSQL-only partial unique index
        (see ``models/product_hub.py`` module docstring): every caller that flips
        ``is_default`` must go through here so at most one default variant ever exists
        per product, on every supported dialect including the SQLite test suite.
        """
        with self._scope() as session:
            variant = session.get(ProductVariant, variant_id)
            if variant is None:
                raise KeyError(f"Variant {variant_id} not found")
            others = session.scalars(
                select(ProductVariant).where(
                    ProductVariant.product_id == variant.product_id,
                    ProductVariant.id != variant.id,
                    ProductVariant.is_default.is_(True),
                )
            )
            for other in others:
                other.is_default = False
            variant.is_default = True
            session.flush()
            return variant

    # -- identifiers --------------------------------------------------------

    def list_identifiers(
        self, *, product_id: uuid.UUID | None = None, variant_id: uuid.UUID | None = None
    ) -> list[ProductIdentifier]:
        if product_id is None and variant_id is None:
            raise ValueError("product_id or variant_id is required")
        with self._scope() as session:
            stmt = select(ProductIdentifier)
            if product_id is not None:
                stmt = stmt.where(ProductIdentifier.product_id == product_id)
            if variant_id is not None:
                stmt = stmt.where(ProductIdentifier.variant_id == variant_id)
            return list(session.scalars(stmt).all())

    def add_identifier(
        self,
        *,
        scheme: str,
        value: str,
        normalized_value: str,
        product_id: uuid.UUID | None = None,
        variant_id: uuid.UUID | None = None,
        market: str = "",
        is_primary: bool = False,
        source: str = "",
    ) -> ProductIdentifier:
        if (product_id is None) == (variant_id is None):
            raise ValueError("exactly one of product_id or variant_id is required")
        with self._scope() as session:
            identifier = ProductIdentifier(
                id=uuid.uuid4(),
                product_id=product_id,
                variant_id=variant_id,
                scheme=scheme,
                value=value,
                normalized_value=normalized_value,
                market=market or None,
                is_primary=is_primary,
                source=source or None,
            )
            session.add(identifier)
            session.flush()
            return identifier

    # -- assets -------------------------------------------------------------

    def list_assets(self, product_id: uuid.UUID) -> list[ProductAsset]:
        with self._scope() as session:
            stmt = (
                select(ProductAsset)
                .where(ProductAsset.product_id == product_id)
                .order_by(ProductAsset.role, ProductAsset.sort_order)
            )
            return list(session.scalars(stmt).all())

    # -- channel mappings / cross-source lookups (used by the PR05 matching engine) --

    def get_channel_mapping(
        self, *, channel: str, entity_type: str, external_id: str
    ) -> ChannelMapping | None:
        with self._scope() as session:
            return session.scalar(
                select(ChannelMapping).where(
                    ChannelMapping.channel == channel,
                    ChannelMapping.entity_type == entity_type,
                    ChannelMapping.external_id == external_id,
                )
            )

    def find_identifier(self, *, scheme: str, normalized_value: str) -> ProductIdentifier | None:
        with self._scope() as session:
            return session.scalar(
                select(ProductIdentifier).where(
                    ProductIdentifier.scheme == scheme,
                    ProductIdentifier.normalized_value == normalized_value,
                )
            )

    # -- internal -------------------------------------------------------------

    def _generate_unique_slug(self, session: Session, base_text: str) -> str:
        base_slug = slugify(base_text)
        candidate = base_slug
        suffix = 2
        while session.scalar(select(Product.id).where(Product.slug == candidate)) is not None:
            candidate = f"{base_slug}-{suffix}"
            suffix += 1
        return candidate
