"""Product Hub edit API service layer (PR09/PR10).

Every mutation here runs inside one DB transaction (via ``session_scope``) and writes
exactly one :class:`~xw_office.models.product_hub.AuditLog` row *and* one
:class:`~xw_office.models.product_hub_sync.OutboxEvent` row alongside the business
change — matching the pattern already established by ``grouping.py`` (PR06) for
audit, and the build plan's PR10 "Outbox-Regel" (business change + outbox event in
the *same* transaction) for the outbox. Optimistic locking (``expected_row_version``
-> :class:`OptimisticLockError` -> HTTP 409 at the router layer) is enforced by the
repository methods this service calls, not here.

Scope (per docs/product_hub build plan PR09): product/variant fields, tags,
identifiers, asset metadata, prices (append-only, never mutated in place), print
rules, and the improvement/edition workflow. Outbox events are written here but
nothing consumes them yet — no handler is registered until PR11's Wix push adapter.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import (
    PrintRule,
    Product,
    ProductAsset,
    ProductEdition,
    ProductIdentifier,
    ProductImprovement,
    ProductPrice,
    ProductSkuAlias,
    ProductVariant,
    Tag,
)
from xw_office.repositories.product_hub import (
    OptimisticLockError,
    ProductHubRepository,
    normalize_sku,
)
from xw_office.repositories.product_hub_sync import append_outbox_event

#: Fields the edit API allows on each entity — an explicit allowlist so a stray/renamed
#: kwarg from a request body fails fast with a clear 400 instead of silently touching an
#: unrelated column (the repository's own ``hasattr`` check would otherwise accept any
#: real attribute name, including ones that must stay system-managed).
PRODUCT_EDITABLE_FIELDS = frozenset(
    {
        "name",
        "short_description",
        "description",
        "category",
        "status",
        "active",
        "product_type",
        "brand_name",
        "release_date",
    }
)
VARIANT_EDITABLE_FIELDS = frozenset({"name", "active", "stock_enabled", "weight_grams"})
ASSET_EDITABLE_FIELDS = frozenset({"role", "sort_order"})
PRINT_RULE_EDITABLE_FIELDS = frozenset(
    {
        "min_stock_target",
        "reprint_batch_qty",
        "print_profile_id",
        "print_plan",
        "primary_print_asset_id",
    }
)
IMPROVEMENT_EDITABLE_FIELDS = frozenset({"title", "description", "severity", "status"})


class UnknownFieldError(ValueError):
    """Raised when a request tries to edit a field outside the allowlist above."""


def _check_allowed(changes: dict[str, object], allowed: frozenset[str], *, entity: str) -> None:
    unknown = set(changes) - allowed
    if unknown:
        raise UnknownFieldError(f"Cannot edit {entity} field(s): {', '.join(sorted(unknown))}")


class EditingService:
    """Write side of the Product Hub edit API — one method per editable concern."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- product / variant ------------------------------------------------------

    def update_product(
        self,
        product_id: uuid.UUID,
        *,
        expected_row_version: int,
        changes: dict[str, object],
        actor: str = "",
    ) -> Product:
        _check_allowed(changes, PRODUCT_EDITABLE_FIELDS, entity="product")
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            updated = repo.update_product(
                product_id, expected_row_version=expected_row_version, **changes
            )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product_id,
                action="update",
                changed_fields=sorted(changes),
                after_data={k: str(v) for k, v in changes.items()},
            )
            append_outbox_event(
                session,
                aggregate_type="product",
                aggregate_id=product_id,
                event_type="product.updated",
                payload={k: str(v) for k, v in changes.items()},
            )
            return updated

    def rename_product_sku(
        self, product_id: uuid.UUID, *, expected_row_version: int, sku: str, actor: str = ""
    ) -> Product:
        """Rename a Hub SKU and its matching sellable variant without losing the old lookup."""
        new_sku = normalize_sku(sku)
        if not new_sku:
            raise ValueError("SKU darf nicht leer sein")
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            product = session.get(Product, product_id)
            if product is None:
                raise KeyError(f"Product {product_id} not found")
            if product.row_version != expected_row_version:
                raise OptimisticLockError(
                    f"Product {product_id} row_version is {product.row_version}, "
                    f"expected {expected_row_version}"
                )
            old_sku = normalize_sku(product.sku)
            if new_sku == old_sku:
                return product
            product_match = session.scalar(
                select(Product.id).where(
                    func.upper(Product.sku) == new_sku, Product.id != product_id
                )
            )
            variant_match = session.scalar(
                select(ProductVariant.id).where(func.upper(ProductVariant.sku) == new_sku)
            )
            alias_match = session.scalar(
                select(ProductSkuAlias).where(func.upper(ProductSkuAlias.alias_sku) == new_sku)
            )
            if product_match is not None or variant_match is not None or alias_match is not None:
                raise ValueError(f"SKU {new_sku} ist bereits vergeben")

            variants = list(
                session.scalars(
                    select(ProductVariant).where(ProductVariant.product_id == product_id)
                )
            )
            matching_variants = [
                variant for variant in variants if normalize_sku(variant.sku) == old_sku
            ]
            product.sku = new_sku
            product.row_version += 1
            product.updated_at = datetime.datetime.now(datetime.timezone.utc)
            for variant in matching_variants:
                variant.sku = new_sku
                variant.row_version += 1
                variant.updated_at = datetime.datetime.now(datetime.timezone.utc)
            old_alias = session.scalar(
                select(ProductSkuAlias).where(func.upper(ProductSkuAlias.alias_sku) == old_sku)
            )
            if old_alias is not None and old_alias.product_id != product_id:
                raise ValueError(
                    f"Bisherige SKU {old_sku} ist bereits Alias eines anderen Produkts"
                )
            if old_alias is None:
                session.add(
                    ProductSkuAlias(
                        product_id=product_id,
                        variant_id=matching_variants[0].id if matching_variants else None,
                        alias_sku=old_sku,
                        source="sku_rename",
                    )
                )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product_id,
                action="sku.rename",
                changed_fields=["sku"],
                before_data={"sku": old_sku},
                after_data={"sku": new_sku},
            )
            append_outbox_event(
                session,
                aggregate_type="product",
                aggregate_id=product_id,
                event_type="product.sku_renamed",
                payload={"old_sku": old_sku, "sku": new_sku},
            )
            session.flush()
            return product

    def update_variant(
        self,
        variant_id: uuid.UUID,
        *,
        expected_row_version: int,
        changes: dict[str, object],
        actor: str = "",
    ) -> ProductVariant:
        _check_allowed(changes, VARIANT_EDITABLE_FIELDS, entity="variant")
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            updated = repo.update_variant(
                variant_id, expected_row_version=expected_row_version, **changes
            )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product_variant",
                entity_id=variant_id,
                action="update",
                changed_fields=sorted(changes),
                after_data={k: str(v) for k, v in changes.items()},
            )
            append_outbox_event(
                session,
                aggregate_type="product",
                aggregate_id=updated.product_id,
                event_type="product.updated",
                payload={"variant_id": str(variant_id), **{k: str(v) for k, v in changes.items()}},
            )
            return updated

    # -- tags / identifiers -------------------------------------------------------

    def add_tag(self, product_id: uuid.UUID, *, tag_code: str, actor: str = "") -> Tag:
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            tag = repo.find_tag_by_code(tag_code)
            if tag is None:
                raise KeyError(f"Tag '{tag_code}' does not exist")
            repo.add_product_tag(product_id=product_id, tag_id=tag.id)
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product_id,
                action="add_tag",
                changed_fields=["tags"],
                after_data={"tag_code": tag_code},
            )
            append_outbox_event(
                session,
                aggregate_type="product",
                aggregate_id=product_id,
                event_type="product.updated",
                payload={"tags_added": [tag_code]},
            )
            return tag

    def remove_tag(self, product_id: uuid.UUID, *, tag_id: uuid.UUID, actor: str = "") -> None:
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            repo.remove_product_tag(product_id=product_id, tag_id=tag_id)
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product_id,
                action="remove_tag",
                changed_fields=["tags"],
                before_data={"tag_id": str(tag_id)},
            )
            append_outbox_event(
                session,
                aggregate_type="product",
                aggregate_id=product_id,
                event_type="product.updated",
                payload={"tags_removed": [str(tag_id)]},
            )

    def add_identifier(
        self,
        product_id: uuid.UUID,
        *,
        scheme: str,
        value: str,
        variant_id: uuid.UUID | None = None,
        market: str = "",
        is_primary: bool = False,
        actor: str = "",
    ) -> ProductIdentifier:
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            identifier = repo.add_identifier(
                scheme=scheme,
                value=value,
                normalized_value=value.strip().upper(),
                product_id=None if variant_id else product_id,
                variant_id=variant_id,
                market=market,
                is_primary=is_primary,
                source="manual",
            )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product_id,
                action="add_identifier",
                changed_fields=["identifiers"],
                after_data={"scheme": scheme, "value": value},
            )
            append_outbox_event(
                session,
                aggregate_type="product",
                aggregate_id=product_id,
                event_type="product.updated",
                payload={"identifier_added": {"scheme": scheme, "value": value}},
            )
            return identifier

    def remove_identifier(
        self, product_id: uuid.UUID, *, identifier_id: uuid.UUID, actor: str = ""
    ) -> None:
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            repo.remove_identifier(identifier_id)
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product_id,
                action="remove_identifier",
                changed_fields=["identifiers"],
                before_data={"identifier_id": str(identifier_id)},
            )
            append_outbox_event(
                session,
                aggregate_type="product",
                aggregate_id=product_id,
                event_type="product.updated",
                payload={"identifier_removed": str(identifier_id)},
            )

    # -- assets / print rules ------------------------------------------------------

    def update_asset(
        self,
        asset_id: uuid.UUID,
        *,
        expected_row_version: int,
        changes: dict[str, object],
        actor: str = "",
    ) -> ProductAsset:
        _check_allowed(changes, ASSET_EDITABLE_FIELDS, entity="asset")
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            updated = repo.update_asset(
                asset_id, expected_row_version=expected_row_version, **changes
            )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product_asset",
                entity_id=asset_id,
                action="update",
                changed_fields=sorted(changes),
                after_data={k: str(v) for k, v in changes.items()},
            )
            append_outbox_event(
                session,
                aggregate_type="product_asset",
                aggregate_id=asset_id,
                event_type="asset.changed",
                payload={k: str(v) for k, v in changes.items()},
            )
            return updated

    def upsert_print_rule(
        self,
        variant_id: uuid.UUID,
        *,
        expected_row_version: int | None,
        changes: dict[str, object],
        actor: str = "",
    ) -> PrintRule:
        _check_allowed(changes, PRINT_RULE_EDITABLE_FIELDS, entity="print rule")
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            updated = repo.upsert_print_rule(
                variant_id, expected_row_version=expected_row_version, **changes
            )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="print_rule",
                entity_id=updated.id,
                action="upsert",
                changed_fields=sorted(changes),
                after_data={k: str(v) for k, v in changes.items()},
            )
            append_outbox_event(
                session,
                aggregate_type="print_rule",
                aggregate_id=updated.id,
                event_type="print_rule.updated",
                payload={k: str(v) for k, v in changes.items()},
            )
            return updated

    def set_price(
        self,
        variant_id: uuid.UUID,
        *,
        price_list_code: str,
        net_amount: Decimal | None = None,
        gross_amount: Decimal | None = None,
        tax_rate: Decimal | None = None,
        currency: str = "EUR",
        actor: str = "",
    ) -> ProductPrice:
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            price_list = repo.get_price_list_by_code(price_list_code)
            if price_list is None:
                raise KeyError(f"Price list '{price_list_code}' does not exist")
            price = repo.set_price(
                variant_id,
                price_list_id=price_list.id,
                currency=currency,
                net_amount=net_amount,
                gross_amount=gross_amount,
                tax_rate=tax_rate,
                source="manual",
            )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product_variant",
                entity_id=variant_id,
                action="price.changed",
                changed_fields=["price"],
                after_data={
                    "price_list_code": price_list_code,
                    "net_amount": str(net_amount) if net_amount is not None else None,
                    "gross_amount": str(gross_amount) if gross_amount is not None else None,
                },
            )
            append_outbox_event(
                session,
                aggregate_type="product_variant",
                aggregate_id=variant_id,
                event_type="price.changed",
                payload={
                    "price_list_code": price_list_code,
                    "net_amount": str(net_amount) if net_amount is not None else None,
                    "gross_amount": str(gross_amount) if gross_amount is not None else None,
                },
            )
            return price

    # -- improvements / editions --------------------------------------------------

    def create_improvement(
        self,
        product_id: uuid.UUID,
        *,
        description: str,
        variant_id: uuid.UUID | None = None,
        title: str = "",
        severity: str = "minor",
        actor: str = "",
    ) -> ProductImprovement:
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            improvement = repo.create_improvement(
                product_id=product_id,
                variant_id=variant_id,
                title=title,
                description=description,
                source="user" if actor else "internal",
                severity=severity,
            )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product_id,
                action="add_improvement",
                changed_fields=["improvements"],
                after_data={"description": description, "severity": severity},
            )
            append_outbox_event(
                session,
                aggregate_type="product",
                aggregate_id=product_id,
                event_type="improvement.created",
                payload={"description": description, "severity": severity},
            )
            return improvement

    def update_improvement(
        self,
        improvement_id: uuid.UUID,
        *,
        expected_row_version: int,
        changes: dict[str, object],
        actor: str = "",
    ) -> ProductImprovement:
        _check_allowed(changes, IMPROVEMENT_EDITABLE_FIELDS, entity="improvement")
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            if changes.get("status") == "resolved":
                changes = {**changes, "resolved_at": datetime.datetime.now(datetime.timezone.utc)}
            updated = repo.update_improvement(
                improvement_id, expected_row_version=expected_row_version, **changes
            )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product_improvement",
                entity_id=improvement_id,
                action="update",
                changed_fields=sorted(changes),
                after_data={k: str(v) for k, v in changes.items()},
            )
            append_outbox_event(
                session,
                aggregate_type="product_improvement",
                aggregate_id=improvement_id,
                event_type="improvement.updated",
                payload={k: str(v) for k, v in changes.items()},
            )
            return updated

    def create_edition(
        self,
        product_id: uuid.UUID,
        *,
        label: str,
        edition_number: int | None = None,
        notes: str = "",
        resolve_improvement_ids: list[uuid.UUID] | None = None,
        actor: str = "",
    ) -> ProductEdition:
        """Create a new edition and, in the same transaction, resolve any open
        improvements the caller chose to fold into it — matching the build plan's
        "neue Auflage" step (new edition + assign open improvements)."""
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            edition = repo.create_edition(
                product_id=product_id, label=label, edition_number=edition_number, notes=notes
            )
            resolved_ids = resolve_improvement_ids or []
            if resolved_ids:
                repo.assign_improvements_to_edition(edition.id, resolved_ids)
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product_id,
                action="create_edition",
                changed_fields=["editions"],
                after_data={"label": label, "resolved_improvement_count": str(len(resolved_ids))},
            )
            append_outbox_event(
                session,
                aggregate_type="product_edition",
                aggregate_id=edition.id,
                event_type="edition.created",
                payload={"product_id": str(product_id), "label": label},
            )
            return edition

    def set_bullet_points(
        self,
        product_id: uuid.UUID,
        *,
        bullet_points: list[str],
        expected_row_version: int,
        actor: str = "",
    ) -> Product:
        """Save bullet points (e.g. from the OpenAI content generator) into
        ``product.attributes`` — not yet a first-class column, so this only ever
        touches that one key, never the rest of ``attributes``."""
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            product = repo.get_product(product_id)
            if product is None:
                raise KeyError(f"Product {product_id} not found")
            merged_attributes = {**product.attributes, "bullet_points": bullet_points}
            updated = repo.update_product(
                product_id, expected_row_version=expected_row_version, attributes=merged_attributes
            )
            repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product_id,
                action="set_bullet_points",
                changed_fields=["bullet_points"],
                after_data={"bullet_points": bullet_points},
            )
            append_outbox_event(
                session,
                aggregate_type="product",
                aggregate_id=product_id,
                event_type="product.updated",
                payload={"bullet_points": bullet_points},
            )
            return updated
