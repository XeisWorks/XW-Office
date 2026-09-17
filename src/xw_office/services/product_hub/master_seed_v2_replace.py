"""Safe, repeatable replace of the legacy (V1) master-seed catalog with V2.

V1 (2026-09-16) was imported from the wrong worksheet and then, in a second pass, from
a reconciled-but-still-flat 972-row master-seed CSV. V2 replaces it with a corrected,
canonically-SKU'd, curated-grouped 915-row seed. Deleting and re-staging 900+ products
by hand (ad-hoc SQL) is exactly the kind of one-off operation this module exists to
avoid repeating: :func:`check_catalog_replaceable` verifies the current catalog is
*purely* the automated V1 import (no manual edits to lose) before
:func:`delete_legacy_master_seed_catalog` touches anything, and both are safe to run
again (the check just re-confirms an empty/already-replaced catalog; delete on an empty
catalog is a no-op).

Deletion order respects the FK ``RESTRICT`` constraints in
``models/product_hub.py``/``models/product_hub_inventory.py``: inventory ledger rows,
then ``product_improvement``/``product_edition`` (RESTRICT on ``product``/
``product_variant``), then ``product_variant`` (RESTRICT on ``product``), then
``product``. ``channel_mapping`` and ``audit_log`` carry no DB-level FK to ``product``
(generic ``entity_type``/``entity_id`` polymorphic references) — ``channel_mapping`` is
still deleted here since it's 1:1 tied to the V1 product identities being replaced (V2's
own commit step recreates correct mappings from ``wix_handle_id``); ``audit_log`` is
deliberately *not* deleted — it is a permanent, append-only history, and an entry
referencing a since-deleted product id is a normal, expected shape for an audit log.

``product_identifier``/``product_price``/``product_category``/``product_tag``/
``product_asset``/``print_rule`` are all declared ``ON DELETE CASCADE`` and would
normally be cleaned up by Postgres automatically — this function deletes them
explicitly anyway rather than relying on that. Confirmed the hard way: a first version
of this function that only deleted ``product``/``product_variant`` passed every test
against SQLite (which does not enforce/cascade FK deletes without an explicit
``PRAGMA foreign_keys=ON`` most test setups never turn on) but silently left every
child row orphaned — invisible in a single run, but a second run's own matching engine
then found those orphaned identifiers and proposed merging into their now-deleted
products. Explicit deletes make this correct regardless of which DB backend enforces
what.

Never touches anything outside the Product Hub schema. Deliberately does **not**
delete from ``inventory_movement`` (unlike ``inventory_stock``/``inventory_alert``):
migration ``002_product_pipeline`` already created a *legacy*, unrelated
``product_id``-keyed ``inventory_movement`` table (the desktop app's original stock
ledger) years before PR13/14's variant-keyed shadow-mode ledger of the same name was
designed; migration ``014_product_hub_inventory``'s own ``if "inventory_movement" not
in existing_tables`` guard then silently skipped creating PR13/14's real table in
production, since a table with that name already existed. The two schemas are
incompatible (no ``variant_id`` column on the legacy one) — deleting through the
PR13/14 ORM model against the real, legacy table fails outright. This was caught
during this module's own dry run against production; see
``docs/product_hub/PROGRESS.md`` for the finding. Fixing the underlying name
collision (e.g. renaming PR13/14's table in a new migration) is a separate, follow-up
concern — out of scope here since PR13/14 is unrelated to the Master Seed replace and
the legacy table is confirmed empty (0 rows) in production, so simply not touching it
is safe.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, Delete, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import (
    AuditLog,
    ChannelMapping,
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
)
from xw_office.models.product_hub_inventory import InventoryAlert, InventoryStock
from xw_office.repositories.product_hub import ProductHubRepository

#: The only ``audit_log.action`` values the automated import + curated-grouping
#: pipeline ever writes for ``product``/``product_variant`` (import_commit.py's
#: ``create_from_staging``/``commit_approved_match``, and grouping.py's own
#: ``move_variant_to_product``/``group_products_into_parent*`` — running the grouping
#: step is itself part of this same automated replace pipeline, not a manual edit).
#: Anything else present means a human touched the catalog after import — a signal to
#: stop and diff, not delete.
_AUTOMATED_PIPELINE_ACTIONS = frozenset(
    {
        "create_from_staging",
        "commit_approved_match",
        "move_variant_to_product",
        "group_products_into_parent",
        "group_products_into_parent_receive",
    }
)


@dataclass(frozen=True)
class ReplaceabilityCheck:
    product_count: int
    variant_count: int
    non_automated_audit_actions: list[str]
    #: True only if every audit_log entry for product/product_variant is one of the
    #: automated import actions above — i.e. nothing manual happened since V1 landed.
    is_safe_to_replace: bool

    @property
    def blocking_reason(self) -> str | None:
        if self.is_safe_to_replace:
            return None
        return (
            f"Catalog has {len(self.non_automated_audit_actions)} non-automated audit "
            f"action(s) since import: {sorted(set(self.non_automated_audit_actions))} — "
            "manual changes may exist, refusing to blind-delete. Diff and migrate them "
            "into V2 first."
        )


def check_catalog_replaceable(session_factory: sessionmaker[Session]) -> ReplaceabilityCheck:
    with session_scope(session_factory) as session:
        product_count = int(session.scalar(select(func.count(Product.id))) or 0)
        variant_count = int(session.scalar(select(func.count(ProductVariant.id))) or 0)
        non_automated = list(
            session.scalars(
                select(AuditLog.action).where(
                    AuditLog.entity_type.in_(("product", "product_variant")),
                    AuditLog.action.notin_(_AUTOMATED_PIPELINE_ACTIONS),
                )
            )
        )
        return ReplaceabilityCheck(
            product_count=product_count,
            variant_count=variant_count,
            non_automated_audit_actions=non_automated,
            is_safe_to_replace=not non_automated,
        )


@dataclass
class DeleteReport:
    products_deleted: int = 0
    variants_deleted: int = 0
    improvements_deleted: int = 0
    editions_deleted: int = 0
    channel_mappings_deleted: int = 0
    inventory_rows_deleted: int = 0
    identifiers_deleted: int = 0
    prices_deleted: int = 0
    categories_deleted: int = 0
    tags_deleted: int = 0
    assets_deleted: int = 0
    print_rules_deleted: int = 0


def delete_legacy_master_seed_catalog(
    session_factory: sessionmaker[Session], *, actor: str = ""
) -> DeleteReport:
    """Delete the entire current Product Hub catalog, FK-safe order. Callers must run
    :func:`check_catalog_replaceable` first and only call this when it reports
    ``is_safe_to_replace`` — this function itself does not re-check, so it can also be
    used in tests that intentionally exercise deletion of a synthetic catalog."""
    report = DeleteReport()
    with session_scope(session_factory) as session:

        def _exec(stmt: Delete) -> int:
            result = cast("CursorResult[Any]", session.execute(stmt))
            return result.rowcount or 0

        variant_ids = list(session.scalars(select(ProductVariant.id)))
        product_ids = list(session.scalars(select(Product.id)))

        # inventory_movement deliberately NOT included here — see module docstring.
        report.inventory_rows_deleted += _exec(delete(InventoryAlert).where(InventoryAlert.variant_id.in_(variant_ids)))
        report.inventory_rows_deleted += _exec(delete(InventoryStock).where(InventoryStock.variant_id.in_(variant_ids)))

        report.improvements_deleted = _exec(
            delete(ProductImprovement).where(ProductImprovement.product_id.in_(product_ids))
        )
        report.editions_deleted = _exec(delete(ProductEdition).where(ProductEdition.product_id.in_(product_ids)))

        # Declared ON DELETE CASCADE in Postgres, but deleted explicitly here anyway —
        # see module docstring for why (SQLite doesn't enforce/cascade FK deletes by
        # default, which silently orphaned these rows in an earlier version of this
        # function).
        report.print_rules_deleted = _exec(delete(PrintRule).where(PrintRule.variant_id.in_(variant_ids)))
        report.prices_deleted = _exec(delete(ProductPrice).where(ProductPrice.variant_id.in_(variant_ids)))
        report.identifiers_deleted = _exec(
            delete(ProductIdentifier).where(
                ProductIdentifier.product_id.in_(product_ids) | ProductIdentifier.variant_id.in_(variant_ids)
            )
        )
        report.assets_deleted = _exec(
            delete(ProductAsset).where(
                ProductAsset.product_id.in_(product_ids) | ProductAsset.variant_id.in_(variant_ids)
            )
        )
        report.categories_deleted = _exec(delete(ProductCategory).where(ProductCategory.product_id.in_(product_ids)))
        report.tags_deleted = _exec(delete(ProductTag).where(ProductTag.product_id.in_(product_ids)))

        report.channel_mappings_deleted = _exec(
            delete(ChannelMapping).where(
                ChannelMapping.entity_type == "product", ChannelMapping.internal_entity_id.in_(product_ids)
            )
        )

        # product_sku_alias CASCADEs with product, but delete explicitly first so a
        # partial/aborted V1 alias experiment never blocks the variant/product delete.
        _exec(delete(ProductSkuAlias).where(ProductSkuAlias.product_id.in_(product_ids)))

        report.variants_deleted = _exec(delete(ProductVariant).where(ProductVariant.product_id.in_(product_ids)))
        report.products_deleted = _exec(delete(Product).where(Product.id.in_(product_ids)))

    ProductHubRepository(session_factory).record_audit(
        actor_type="user" if actor else "system",
        actor_id=actor,
        entity_type="product_hub_catalog",
        entity_id=uuid.uuid4(),
        action="master_seed_v2_replace_delete_legacy",
        after_data={
            "products_deleted": report.products_deleted,
            "variants_deleted": report.variants_deleted,
            "improvements_deleted": report.improvements_deleted,
            "channel_mappings_deleted": report.channel_mappings_deleted,
        },
    )
    return report
