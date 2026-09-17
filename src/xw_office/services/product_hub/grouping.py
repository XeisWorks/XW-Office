"""Curated product/variant grouping (PR06, second half).

Groups previously, separately-imported single-variant products into one parent
product with multiple variants — the confirmed *second step* of the "safe migration
rule": every known SKU is first imported as its own product (PR01–PR06's commit
service), and only afterwards are fachlich zusammengehörige products (e.g.
MusikHeroes instrument variants) explicitly, manually grouped here. Never automatic
or fuzzy — grouping candidates come from a human (or a future, separate curated
grouping-candidate report), never from this service itself.

Preserves SKU, identifiers, prices, channel mappings and assets, per
docs/product_hub/XW_PRODUCT_HUB_IMPLEMENTATION.yaml ``curated_grouping.preserve``.
Child products are archived (soft-deleted), never hard-deleted, so their history and
any external references stay intact.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import ProductVariant
from xw_office.repositories.product_hub import ProductHubRepository


class GroupingConflictError(RuntimeError):
    """Raised when a grouping would silently overwrite an existing channel mapping.

    Nothing is written when this is raised — the conflict check runs entirely before
    any write in the same transaction, so an abort here always leaves state untouched.
    """


@dataclass(frozen=True)
class GroupingPreview:
    """What :meth:`GroupingService.group_products_into_parent` would do — no writes."""

    parent_product_id: uuid.UUID
    child_product_ids: list[uuid.UUID]
    variants_to_move: int
    identifiers_to_move: int
    assets_to_move: int
    channel_mapping_conflicts: list[str]

    @property
    def is_safe(self) -> bool:
        return not self.channel_mapping_conflicts


@dataclass
class GroupingResult:
    """Outcome of one successful :meth:`GroupingService.group_products_into_parent` call."""

    parent_product_id: uuid.UUID
    archived_child_product_ids: list[uuid.UUID] = field(default_factory=list)
    variants_moved: int = 0
    identifiers_moved: int = 0
    assets_moved: int = 0
    categories_moved: int = 0
    tags_moved: int = 0
    channel_mappings_moved: int = 0


class GroupingService:
    """Explicit, audited re-parenting of variants/products — no fuzzy auto-merge."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def move_variant_to_product(
        self, variant_id: uuid.UUID, *, target_product_id: uuid.UUID, actor: str = ""
    ) -> ProductVariant:
        """Re-parent one variant. The low-level primitive behind curated grouping."""
        with session_scope(self._session_factory) as session:
            product_repo = ProductHubRepository(session)
            variant = product_repo.get_variant(variant_id)
            if variant is None:
                raise KeyError(f"Variant {variant_id} not found")
            source_product_id = variant.product_id
            updated = product_repo.move_variant(variant_id, target_product_id=target_product_id)
            product_repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product_variant",
                entity_id=variant_id,
                action="move_variant_to_product",
                before_data={"product_id": str(source_product_id)},
                after_data={"product_id": str(target_product_id)},
            )
            return updated

    def preview_grouping(
        self, *, parent_product_id: uuid.UUID, child_product_ids: list[uuid.UUID]
    ) -> GroupingPreview:
        with session_scope(self._session_factory) as session:
            product_repo = ProductHubRepository(session)
            conflicts = self._channel_mapping_conflicts(product_repo, parent_product_id, child_product_ids)
            variants = identifiers = assets = 0
            for child_id in child_product_ids:
                variants += len(product_repo.list_variants(child_id))
                identifiers += len(product_repo.list_identifiers(product_id=child_id))
                assets += len(product_repo.list_assets(child_id))
            return GroupingPreview(
                parent_product_id=parent_product_id,
                child_product_ids=list(child_product_ids),
                variants_to_move=variants,
                identifiers_to_move=identifiers,
                assets_to_move=assets,
                channel_mapping_conflicts=conflicts,
            )

    def group_products_into_parent(
        self, *, parent_product_id: uuid.UUID, child_product_ids: list[uuid.UUID], actor: str = ""
    ) -> GroupingResult:
        if parent_product_id in child_product_ids:
            raise ValueError("parent_product_id must not also be one of the child_product_ids")
        if not child_product_ids:
            raise ValueError("child_product_ids must not be empty")

        with session_scope(self._session_factory) as session:
            product_repo = ProductHubRepository(session)
            parent = product_repo.get_product(parent_product_id)
            if parent is None:
                raise KeyError(f"Parent product {parent_product_id} not found")

            # Pre-check phase: pure reads only. If this raises, nothing below has run
            # and nothing was written — a clean abort, per "bei Konflikt abbrechen".
            conflicts = self._channel_mapping_conflicts(product_repo, parent_product_id, child_product_ids)
            if conflicts:
                raise GroupingConflictError(
                    "Grouping aborted, no changes made — resolve first: " + "; ".join(conflicts)
                )
            for child_id in child_product_ids:
                if product_repo.get_product(child_id) is None:
                    raise KeyError(f"Child product {child_id} not found")

            result = GroupingResult(parent_product_id=parent_product_id)
            parent_default = product_repo.get_default_variant(parent_product_id)

            for child_id in child_product_ids:
                for variant in product_repo.list_variants(child_id):
                    was_default = variant.is_default
                    # move_variant() always clears is_default on the moved variant -
                    # only promote it below if the parent doesn't already have one.
                    product_repo.move_variant(variant.id, target_product_id=parent_product_id)
                    result.variants_moved += 1
                    if was_default and parent_default is None:
                        # Parent had no variant of its own yet - keep this one default
                        # and remember it, in case a later child also arrives default.
                        parent_default = product_repo.set_default_variant(variant.id)

                for identifier in product_repo.list_identifiers(product_id=child_id):
                    product_repo.reparent_identifier(identifier.id, product_id=parent_product_id)
                    result.identifiers_moved += 1

                for asset in product_repo.list_assets(child_id):
                    product_repo.reparent_asset(asset.id, product_id=parent_product_id)
                    result.assets_moved += 1

                for link in product_repo.list_product_categories(child_id):
                    product_repo.add_product_category(
                        product_id=parent_product_id,
                        category_id=link.category_id,
                        is_primary=link.is_primary,
                    )
                    result.categories_moved += 1
                product_repo.remove_product_categories(child_id)

                for tag_link in product_repo.list_product_tags(child_id):
                    product_repo.add_product_tag(product_id=parent_product_id, tag_id=tag_link.tag_id)
                    result.tags_moved += 1
                product_repo.remove_product_tags(child_id)

                for mapping in product_repo.list_channel_mappings(
                    entity_type="product", internal_entity_id=child_id
                ):
                    product_repo.reparent_channel_mapping(mapping.id, internal_entity_id=parent_product_id)
                    result.channel_mappings_moved += 1

                product_repo.archive_product(child_id)
                result.archived_child_product_ids.append(child_id)

                product_repo.record_audit(
                    actor_type="user" if actor else "system",
                    actor_id=actor,
                    entity_type="product",
                    entity_id=child_id,
                    action="group_products_into_parent",
                    before_data={"active": True},
                    after_data={"active": False, "grouped_into": str(parent_product_id)},
                )

            product_repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=parent_product_id,
                action="group_products_into_parent_receive",
                after_data={"child_product_ids": [str(child_id) for child_id in child_product_ids]},
            )
            return result

    @staticmethod
    def _channel_mapping_conflicts(
        product_repo: ProductHubRepository,
        parent_product_id: uuid.UUID,
        child_product_ids: list[uuid.UUID],
    ) -> list[str]:
        parent_channels = {
            mapping.channel
            for mapping in product_repo.list_channel_mappings(
                entity_type="product", internal_entity_id=parent_product_id
            )
        }
        conflicts: list[str] = []
        for child_id in child_product_ids:
            for mapping in product_repo.list_channel_mappings(
                entity_type="product", internal_entity_id=child_id
            ):
                if mapping.channel in parent_channels:
                    conflicts.append(
                        f"child {child_id} has its own {mapping.channel} mapping "
                        f"({mapping.external_id}) — parent already has one too"
                    )
        return conflicts
