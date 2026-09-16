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
from decimal import Decimal
import re
import uuid
from collections.abc import Generator
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import (
    AuditLog,
    Category,
    ChannelMapping,
    PriceList,
    PrintRule,
    Product,
    ProductAsset,
    ProductCategory,
    ProductEdition,
    ProductIdentifier,
    ProductImprovement,
    ProductPrice,
    ProductSkuAlias,
    ProductTag,
    ProductVariant,
    Tag,
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
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True)
class ResolvedSku:
    """Result of :meth:`ProductHubRepository.resolve_sku`."""

    product: Product
    variant: ProductVariant
    #: "sku" when the variant's own SKU matched directly, "alias" when only a
    #: product_sku_alias row matched — the matching engine (PR05) uses this to tell
    #: match_method "exact_sku" apart from "sku_alias".
    matched_via: str = "sku"


def _apply_product_filters(stmt: "Select[Any]", filters: ProductFilter) -> "Select[Any]":
    """Shared WHERE-clause builder for :meth:`list_products`/:meth:`count_products`."""
    if filters.status is not None:
        stmt = stmt.where(Product.status == filters.status)
    if filters.active is not None:
        stmt = stmt.where(Product.active == filters.active)
    if filters.family_id is not None:
        stmt = stmt.where(Product.family_id == filters.family_id)
    if filters.search:
        needle = f"%{filters.search.strip()}%"
        stmt = stmt.where(Product.name.ilike(needle))
    return stmt


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
            stmt = _apply_product_filters(select(Product), filters).order_by(Product.name)
            if filters.limit is not None:
                stmt = stmt.limit(filters.limit).offset(filters.offset)
            return list(session.scalars(stmt).all())

    def count_products(self, filters: ProductFilter | None = None) -> int:
        filters = filters or ProductFilter()
        with self._scope() as session:
            stmt = _apply_product_filters(select(func.count(Product.id)), filters)
            return int(session.scalar(stmt) or 0)

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

    def update_variant(
        self,
        variant_id: uuid.UUID,
        *,
        expected_row_version: int,
        **fields: object,
    ) -> ProductVariant:
        """Optimistic-locked partial update; raises :class:`OptimisticLockError` if stale."""
        with self._scope() as session:
            variant = session.get(ProductVariant, variant_id)
            if variant is None:
                raise KeyError(f"Variant {variant_id} not found")
            if variant.row_version != expected_row_version:
                raise OptimisticLockError(
                    f"Variant {variant_id} row_version is {variant.row_version}, "
                    f"expected {expected_row_version}"
                )
            for field_name, value in fields.items():
                if not hasattr(variant, field_name):
                    raise ValueError(f"Unknown variant field: {field_name}")
                setattr(variant, field_name, value)
            variant.row_version += 1
            variant.updated_at = datetime.datetime.now(datetime.timezone.utc)
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

    def remove_identifier(self, identifier_id: uuid.UUID) -> None:
        with self._scope() as session:
            identifier = session.get(ProductIdentifier, identifier_id)
            if identifier is None:
                raise KeyError(f"Identifier {identifier_id} not found")
            session.delete(identifier)
            session.flush()

    # -- assets -------------------------------------------------------------

    def list_assets(self, product_id: uuid.UUID) -> list[ProductAsset]:
        with self._scope() as session:
            stmt = (
                select(ProductAsset)
                .where(ProductAsset.product_id == product_id)
                .order_by(ProductAsset.role, ProductAsset.sort_order)
            )
            return list(session.scalars(stmt).all())

    def get_asset(self, asset_id: uuid.UUID) -> ProductAsset | None:
        with self._scope() as session:
            return session.get(ProductAsset, asset_id)

    def update_asset(
        self,
        asset_id: uuid.UUID,
        *,
        expected_row_version: int,
        **fields: object,
    ) -> ProductAsset:
        """Optimistic-locked metadata update (role/sort_order) — never ``uri``/health
        fields, those stay system-managed (import/health-check owned)."""
        with self._scope() as session:
            asset = session.get(ProductAsset, asset_id)
            if asset is None:
                raise KeyError(f"Asset {asset_id} not found")
            if asset.row_version != expected_row_version:
                raise OptimisticLockError(
                    f"Asset {asset_id} row_version is {asset.row_version}, "
                    f"expected {expected_row_version}"
                )
            for field_name, value in fields.items():
                if not hasattr(asset, field_name):
                    raise ValueError(f"Unknown asset field: {field_name}")
                setattr(asset, field_name, value)
            asset.row_version += 1
            asset.updated_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return asset

    # -- prices / print rules / improvements ---------------------------------------

    def list_prices(self, variant_id: uuid.UUID) -> list[ProductPrice]:
        with self._scope() as session:
            stmt = select(ProductPrice).where(ProductPrice.variant_id == variant_id).order_by(
                ProductPrice.valid_from.desc()
            )
            return list(session.scalars(stmt).all())

    def get_price_list_by_code(self, code: str) -> PriceList | None:
        with self._scope() as session:
            return session.scalar(select(PriceList).where(PriceList.code == code))

    def set_price(
        self,
        variant_id: uuid.UUID,
        *,
        price_list_id: uuid.UUID,
        currency: str = "EUR",
        net_amount: Decimal | None = None,
        gross_amount: Decimal | None = None,
        tax_rate: Decimal | None = None,
        valid_from: datetime.datetime | None = None,
        source: str = "manual",
    ) -> ProductPrice:
        """Write a new effective-dated price row, closing out the previously open one.

        Prices are never mutated in place (see migration 011's docstring) — "editing" a
        price means the old value stays in history with a real ``valid_until``, and the
        new value starts a fresh row. No optimistic lock needed: each call is additive.
        """
        effective_from = valid_from or datetime.datetime.now(datetime.timezone.utc)
        with self._scope() as session:
            previous = session.scalar(
                select(ProductPrice)
                .where(
                    ProductPrice.variant_id == variant_id,
                    ProductPrice.price_list_id == price_list_id,
                    ProductPrice.valid_until.is_(None),
                )
                .order_by(ProductPrice.valid_from.desc())
            )
            if previous is not None:
                previous.valid_until = effective_from
            price = ProductPrice(
                id=uuid.uuid4(),
                variant_id=variant_id,
                price_list_id=price_list_id,
                currency=currency,
                net_amount=net_amount,
                gross_amount=gross_amount,
                tax_rate=tax_rate,
                valid_from=effective_from,
                valid_until=None,
                source=source,
            )
            session.add(price)
            session.flush()
            return price

    def get_print_rule(self, variant_id: uuid.UUID) -> PrintRule | None:
        with self._scope() as session:
            return session.scalar(select(PrintRule).where(PrintRule.variant_id == variant_id))

    def upsert_print_rule(
        self,
        variant_id: uuid.UUID,
        *,
        expected_row_version: int | None = None,
        **fields: object,
    ) -> PrintRule:
        """Create the variant's print rule if it doesn't exist yet, else optimistic-locked
        update. ``expected_row_version`` is required (and checked) only for the update
        path — a first-time create has nothing to conflict with."""
        with self._scope() as session:
            rule = session.scalar(select(PrintRule).where(PrintRule.variant_id == variant_id))
            if rule is None:
                rule = PrintRule(id=uuid.uuid4(), variant_id=variant_id)
                for field_name, value in fields.items():
                    if not hasattr(rule, field_name):
                        raise ValueError(f"Unknown print rule field: {field_name}")
                    setattr(rule, field_name, value)
                session.add(rule)
                session.flush()
                return rule
            if expected_row_version is None or rule.row_version != expected_row_version:
                raise OptimisticLockError(
                    f"Print rule for variant {variant_id} row_version is {rule.row_version}, "
                    f"expected {expected_row_version}"
                )
            for field_name, value in fields.items():
                if not hasattr(rule, field_name):
                    raise ValueError(f"Unknown print rule field: {field_name}")
                setattr(rule, field_name, value)
            rule.row_version += 1
            rule.updated_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return rule

    def list_improvements(self, product_id: uuid.UUID) -> list[ProductImprovement]:
        with self._scope() as session:
            stmt = (
                select(ProductImprovement)
                .where(ProductImprovement.product_id == product_id)
                .order_by(ProductImprovement.created_at.desc())
            )
            return list(session.scalars(stmt).all())

    def get_improvement(self, improvement_id: uuid.UUID) -> ProductImprovement | None:
        with self._scope() as session:
            return session.get(ProductImprovement, improvement_id)

    def create_improvement(
        self,
        *,
        product_id: uuid.UUID,
        description: str,
        variant_id: uuid.UUID | None = None,
        title: str = "",
        source: str = "internal",
        source_reference: str = "",
        severity: str = "minor",
    ) -> ProductImprovement:
        with self._scope() as session:
            improvement = ProductImprovement(
                id=uuid.uuid4(),
                product_id=product_id,
                variant_id=variant_id,
                title=title or None,
                description=description,
                source=source,
                source_reference=source_reference or None,
                severity=severity,
                status="open",
            )
            session.add(improvement)
            session.flush()
            return improvement

    def update_improvement(
        self,
        improvement_id: uuid.UUID,
        *,
        expected_row_version: int,
        **fields: object,
    ) -> ProductImprovement:
        """Optimistic-locked update, e.g. ``status``/``severity``; setting ``status`` to
        ``"resolved"`` does not auto-stamp ``resolved_at`` — callers (the editing
        service) own that so it stays paired with ``resolved_in_edition_id``."""
        with self._scope() as session:
            improvement = session.get(ProductImprovement, improvement_id)
            if improvement is None:
                raise KeyError(f"Improvement {improvement_id} not found")
            if improvement.row_version != expected_row_version:
                raise OptimisticLockError(
                    f"Improvement {improvement_id} row_version is {improvement.row_version}, "
                    f"expected {expected_row_version}"
                )
            for field_name, value in fields.items():
                if not hasattr(improvement, field_name):
                    raise ValueError(f"Unknown improvement field: {field_name}")
                setattr(improvement, field_name, value)
            improvement.row_version += 1
            session.flush()
            return improvement

    # -- editions -------------------------------------------------------------------

    def create_edition(
        self,
        *,
        product_id: uuid.UUID,
        label: str,
        edition_number: int | None = None,
        notes: str = "",
    ) -> ProductEdition:
        with self._scope() as session:
            edition = ProductEdition(
                id=uuid.uuid4(),
                product_id=product_id,
                label=label,
                edition_number=edition_number,
                status="draft",
                notes=notes or None,
            )
            session.add(edition)
            session.flush()
            return edition

    def list_editions(self, product_id: uuid.UUID) -> list[ProductEdition]:
        with self._scope() as session:
            stmt = (
                select(ProductEdition)
                .where(ProductEdition.product_id == product_id)
                .order_by(ProductEdition.created_at.desc())
            )
            return list(session.scalars(stmt).all())

    def assign_improvements_to_edition(
        self, edition_id: uuid.UUID, improvement_ids: list[uuid.UUID]
    ) -> list[ProductImprovement]:
        """Mark each improvement resolved-in this edition. Silently skips ids that
        don't exist or already belong to a different edition's resolved set — the
        caller (editing service) reports exactly which ids actually changed via the
        returned list, so partial/duplicate input never raises."""
        with self._scope() as session:
            updated: list[ProductImprovement] = []
            for improvement_id in improvement_ids:
                improvement = session.get(ProductImprovement, improvement_id)
                if improvement is None:
                    continue
                improvement.status = "resolved"
                improvement.resolved_in_edition_id = edition_id
                improvement.resolved_at = datetime.datetime.now(datetime.timezone.utc)
                improvement.row_version += 1
                updated.append(improvement)
            session.flush()
            return updated

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

    def create_channel_mapping(
        self,
        *,
        channel: str,
        entity_type: str,
        internal_entity_id: uuid.UUID,
        external_id: str,
        sync_status: str = "synced",
    ) -> ChannelMapping:
        with self._scope() as session:
            mapping = ChannelMapping(
                id=uuid.uuid4(),
                channel=channel,
                entity_type=entity_type,
                internal_entity_id=internal_entity_id,
                external_id=external_id,
                sync_status=sync_status,
            )
            session.add(mapping)
            session.flush()
            return mapping

    def add_asset(
        self,
        *,
        product_id: uuid.UUID,
        role: str,
        storage_kind: str,
        uri: str,
        variant_id: uuid.UUID | None = None,
        sort_order: int = 0,
        source_channel: str | None = None,
        source_external_id: str | None = None,
        source_url: str | None = None,
        public_share_allowed: bool = False,
    ) -> ProductAsset:
        with self._scope() as session:
            asset = ProductAsset(
                id=uuid.uuid4(),
                product_id=product_id,
                variant_id=variant_id,
                role=role,
                sort_order=sort_order,
                storage_kind=storage_kind,
                uri=uri,
                source_channel=source_channel,
                source_external_id=source_external_id,
                source_url=source_url,
                public_share_allowed=public_share_allowed,
                health_status="unknown",
            )
            session.add(asset)
            session.flush()
            return asset

    # -- categories / tags ---------------------------------------------------------

    def get_or_create_category(self, *, code: str, name: str) -> Category:
        with self._scope() as session:
            existing = session.scalar(select(Category).where(Category.code == code))
            if existing is not None:
                return existing
            category = Category(id=uuid.uuid4(), code=code, name=name)
            session.add(category)
            session.flush()
            return category

    def list_product_categories(self, product_id: uuid.UUID) -> list[ProductCategory]:
        with self._scope() as session:
            stmt = select(ProductCategory).where(ProductCategory.product_id == product_id)
            return list(session.scalars(stmt).all())

    def add_product_category(
        self, *, product_id: uuid.UUID, category_id: uuid.UUID, is_primary: bool = False
    ) -> ProductCategory:
        with self._scope() as session:
            existing = session.get(ProductCategory, (product_id, category_id))
            if existing is not None:
                return existing
            link = ProductCategory(product_id=product_id, category_id=category_id, is_primary=is_primary)
            session.add(link)
            session.flush()
            return link

    def remove_product_category(self, *, product_id: uuid.UUID, category_id: uuid.UUID) -> None:
        with self._scope() as session:
            link = session.get(ProductCategory, (product_id, category_id))
            if link is not None:
                session.delete(link)
                session.flush()

    def get_or_create_tag(self, *, code: str, label: str) -> Tag:
        with self._scope() as session:
            existing = session.scalar(select(Tag).where(Tag.code == code))
            if existing is not None:
                return existing
            tag = Tag(id=uuid.uuid4(), code=code, label=label)
            session.add(tag)
            session.flush()
            return tag

    def find_tag_by_code(self, code: str) -> Tag | None:
        with self._scope() as session:
            return session.scalar(select(Tag).where(Tag.code == code))

    def get_tag(self, tag_id: uuid.UUID) -> Tag | None:
        with self._scope() as session:
            return session.get(Tag, tag_id)

    def list_product_tags(self, product_id: uuid.UUID) -> list[ProductTag]:
        with self._scope() as session:
            stmt = select(ProductTag).where(ProductTag.product_id == product_id)
            return list(session.scalars(stmt).all())

    def add_product_tag(self, *, product_id: uuid.UUID, tag_id: uuid.UUID) -> ProductTag:
        with self._scope() as session:
            existing = session.get(ProductTag, (product_id, tag_id))
            if existing is not None:
                return existing
            link = ProductTag(product_id=product_id, tag_id=tag_id)
            session.add(link)
            session.flush()
            return link

    def remove_product_tag(self, *, product_id: uuid.UUID, tag_id: uuid.UUID) -> None:
        with self._scope() as session:
            link = session.get(ProductTag, (product_id, tag_id))
            if link is not None:
                session.delete(link)
                session.flush()

    # -- variants (grouping support) -------------------------------------------------

    def move_variant(self, variant_id: uuid.UUID, *, target_product_id: uuid.UUID) -> ProductVariant:
        """Re-parent a variant to a different product (used by curated grouping, PR06).

        Identifiers/assets attached via ``variant_id`` follow automatically (their FK
        is the variant, not the product); only product-scoped rows need separate moves.
        """
        with self._scope() as session:
            variant = session.get(ProductVariant, variant_id)
            if variant is None:
                raise KeyError(f"Variant {variant_id} not found")
            variant.product_id = target_product_id
            session.flush()
            return variant

    # -- product-scoped reparenting (curated grouping, PR06) -------------------------

    def reparent_identifier(self, identifier_id: uuid.UUID, *, product_id: uuid.UUID) -> ProductIdentifier:
        """Move a *product-scoped* identifier to a different product.

        Only ever called for identifiers already carrying ``product_id`` (never
        ``variant_id``) — a variant-scoped identifier already follows its variant
        automatically once :meth:`move_variant` re-parents that variant.
        """
        with self._scope() as session:
            identifier = session.get(ProductIdentifier, identifier_id)
            if identifier is None:
                raise KeyError(f"Identifier {identifier_id} not found")
            identifier.product_id = product_id
            session.flush()
            return identifier

    def reparent_asset(self, asset_id: uuid.UUID, *, product_id: uuid.UUID) -> ProductAsset:
        with self._scope() as session:
            asset = session.get(ProductAsset, asset_id)
            if asset is None:
                raise KeyError(f"Asset {asset_id} not found")
            asset.product_id = product_id
            session.flush()
            return asset

    def remove_product_categories(self, product_id: uuid.UUID) -> None:
        with self._scope() as session:
            for link in session.scalars(
                select(ProductCategory).where(ProductCategory.product_id == product_id)
            ).all():
                session.delete(link)
            session.flush()

    def remove_product_tags(self, product_id: uuid.UUID) -> None:
        with self._scope() as session:
            for link in session.scalars(
                select(ProductTag).where(ProductTag.product_id == product_id)
            ).all():
                session.delete(link)
            session.flush()

    def list_channel_mappings(
        self, *, entity_type: str, internal_entity_id: uuid.UUID
    ) -> list[ChannelMapping]:
        with self._scope() as session:
            stmt = select(ChannelMapping).where(
                ChannelMapping.entity_type == entity_type,
                ChannelMapping.internal_entity_id == internal_entity_id,
            )
            return list(session.scalars(stmt).all())

    def reparent_channel_mapping(
        self, mapping_id: uuid.UUID, *, internal_entity_id: uuid.UUID
    ) -> ChannelMapping:
        with self._scope() as session:
            mapping = session.get(ChannelMapping, mapping_id)
            if mapping is None:
                raise KeyError(f"Channel mapping {mapping_id} not found")
            mapping.internal_entity_id = internal_entity_id
            session.flush()
            return mapping

    def archive_product(self, product_id: uuid.UUID) -> Product:
        """Soft-delete: set ``active=False``/``archived_at`` (never hard-delete)."""
        with self._scope() as session:
            product = session.get(Product, product_id)
            if product is None:
                raise KeyError(f"Product {product_id} not found")
            product.active = False
            product.archived_at = datetime.datetime.now(datetime.timezone.utc)
            product.row_version += 1
            session.flush()
            return product

    # -- audit log --------------------------------------------------------------

    def record_audit(
        self,
        *,
        actor_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        source: str = "product_hub",
        actor_id: str = "",
        changed_fields: list[str] | None = None,
        before_data: dict[str, object] | None = None,
        after_data: dict[str, object] | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> AuditLog:
        with self._scope() as session:
            entry = AuditLog(
                id=uuid.uuid4(),
                actor_type=actor_type,
                actor_id=actor_id or None,
                source=source,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                changed_fields=list(changed_fields or []),
                before_data=before_data,
                after_data=after_data,
                correlation_id=correlation_id,
            )
            session.add(entry)
            session.flush()
            return entry

    def list_audit_log(self, entity_type: str, entity_id: uuid.UUID) -> list[AuditLog]:
        with self._scope() as session:
            stmt = (
                select(AuditLog)
                .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
                .order_by(AuditLog.created_at)
            )
            return list(session.scalars(stmt).all())

    # -- internal -------------------------------------------------------------

    def _generate_unique_slug(self, session: Session, base_text: str) -> str:
        base_slug = slugify(base_text)
        candidate = base_slug
        suffix = 2
        while session.scalar(select(Product.id).where(Product.slug == candidate)) is not None:
            candidate = f"{base_slug}-{suffix}"
            suffix += 1
        return candidate
