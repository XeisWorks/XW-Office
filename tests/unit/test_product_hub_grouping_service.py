"""Tests for the curated product/variant grouping service (PR06, second half)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.grouping import GroupingConflictError, GroupingService


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    # Mirrors ix_product_variant_one_default_per_product (migration 009) - a
    # PostgreSQL-only partial unique index the SQLAlchemy model never declares (see
    # models/product_hub.py's own "PostgreSQL-only partial unique index" comments).
    # Without this, SQLite silently allows two is_default=true variants under one
    # product - exactly the gap that let move_variant()'s missing is_default reset
    # through every existing test until it broke for real against production.
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX ix_test_one_default_variant_per_product "
                "ON product_variant (product_id) WHERE is_default = 1"
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def product_repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


@pytest.fixture
def grouping(session_factory: sessionmaker[Session]) -> GroupingService:
    return GroupingService(session_factory)


def test_move_variant_to_product_reparents_and_audits(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    source, source_variant = product_repo.create_product(sku="XW-1", name="Quelle")
    target, _ = product_repo.create_product(sku="XW-2", name="Ziel")

    moved = grouping.move_variant_to_product(source_variant.id, target_product_id=target.id, actor="tester")

    assert moved.product_id == target.id
    audit = product_repo.list_audit_log("product_variant", source_variant.id)
    assert any(entry.action == "move_variant_to_product" for entry in audit)


def test_move_variant_to_product_clears_is_default_on_the_moved_variant(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    """Regression test for the bug that broke the first real Postgres grouping run:
    every product's sole variant is is_default=True (create_product()'s own
    invariant), so moving it into a product that already has its own default variant
    must never leave two is_default=True rows under the same product_id -
    ix_product_variant_one_default_per_product (Postgres-only, mirrored in this
    file's session_factory fixture for SQLite) would reject exactly that."""
    target, target_variant = product_repo.create_product(sku="XW-1", name="Ziel")
    source, source_variant = product_repo.create_product(sku="XW-2", name="Quelle")
    assert source_variant.is_default is True  # sanity check on the scenario itself

    moved = grouping.move_variant_to_product(source_variant.id, target_product_id=target.id)

    assert moved.is_default is False
    refreshed_target_variant = product_repo.get_variant(target_variant.id)
    assert refreshed_target_variant is not None
    assert refreshed_target_variant.is_default is True


def test_group_products_into_parent_moves_everything_and_archives_children(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, parent_variant = product_repo.create_product(sku="XW-511", name="Ohrwürmer #1 (Trompete)")
    child_a, child_a_variant = product_repo.create_product(sku="XW-511.02", name="Ohrwürmer #1 (Posaune)")
    child_b, child_b_variant = product_repo.create_product(sku="XW-511.08", name="Ohrwürmer #1 (F-Tuba)")

    product_repo.add_identifier(
        product_id=child_a.id, scheme="ISBN13", value="9780000000001", normalized_value="9780000000001"
    )
    product_repo.add_asset(
        product_id=child_b.id, role="COVER", storage_kind="EXTERNAL_URL", uri="https://x/cover.jpg"
    )
    category = product_repo.get_or_create_category(code="musikheroes", name="MusikHeroes")
    product_repo.add_product_category(product_id=child_a.id, category_id=category.id)
    tag = product_repo.get_or_create_tag(code="amazon", label="Amazon")
    product_repo.add_product_tag(product_id=child_b.id, tag_id=tag.id)

    result = grouping.group_products_into_parent(
        parent_product_id=parent.id, child_product_ids=[child_a.id, child_b.id], actor="curator"
    )

    assert result.variants_moved == 2
    assert result.identifiers_moved == 1
    assert result.assets_moved == 1
    assert result.categories_moved == 1
    assert result.tags_moved == 1
    assert set(result.archived_child_product_ids) == {child_a.id, child_b.id}

    # All three original SKUs remain independently resolvable under the parent product.
    all_variants = product_repo.list_variants(parent.id)
    assert {v.sku for v in all_variants} == {"XW-511", "XW-511.02", "XW-511.08"}

    resolved_a = product_repo.resolve_sku("XW-511.02")
    assert resolved_a is not None
    assert resolved_a.product.id == parent.id
    assert resolved_a.variant.id == child_a_variant.id

    resolved_b = product_repo.resolve_sku("XW-511.08")
    assert resolved_b is not None
    assert resolved_b.product.id == parent.id

    # Identifiers/assets/categories/tags moved to the parent, not lost.
    assert len(product_repo.list_identifiers(product_id=parent.id)) == 1
    assert len(product_repo.list_assets(parent.id)) == 1
    assert len(product_repo.list_product_categories(parent.id)) == 1
    assert len(product_repo.list_product_tags(parent.id)) == 1

    # Children are archived (soft-deleted), not hard-deleted.
    refreshed_child_a = product_repo.get_product(child_a.id)
    assert refreshed_child_a is not None
    assert refreshed_child_a.active is False
    assert refreshed_child_a.archived_at is not None

    audit = product_repo.list_audit_log("product", child_a.id)
    assert any(entry.action == "group_products_into_parent" for entry in audit)

    # keep parent_variant reference alive for readability of the setup above
    assert parent_variant.product_id == parent.id


def test_group_products_into_parent_keeps_exactly_one_default_variant(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, parent_variant = product_repo.create_product(sku="XW-521", name="Parent")
    child, child_variant = product_repo.create_product(sku="XW-521.02", name="Child")
    assert parent_variant.is_default is True
    assert child_variant.is_default is True  # each was its own product's default

    grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])

    all_variants = product_repo.list_variants(parent.id)
    default_variants = [v for v in all_variants if v.is_default]
    assert len(default_variants) == 1
    assert default_variants[0].id == parent_variant.id


def test_group_products_into_parent_aborts_on_channel_mapping_conflict(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, _ = product_repo.create_product(sku="XW-601", name="Parent")
    child, child_variant = product_repo.create_product(sku="XW-601.1", name="Child")
    product_repo.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=parent.id, external_id="wix-parent"
    )
    product_repo.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=child.id, external_id="wix-child"
    )

    with pytest.raises(GroupingConflictError):
        grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])

    # Nothing was written: child still owns its variant and is still active.
    refreshed_child = product_repo.get_product(child.id)
    assert refreshed_child is not None
    assert refreshed_child.active is True
    refreshed_variant = product_repo.get_variant(child_variant.id)
    assert refreshed_variant is not None
    assert refreshed_variant.product_id == child.id


def test_preview_grouping_reports_conflict_without_writing(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, _ = product_repo.create_product(sku="XW-701", name="Parent")
    child, _ = product_repo.create_product(sku="XW-701.1", name="Child")
    product_repo.create_channel_mapping(
        channel="sevdesk", entity_type="product", internal_entity_id=parent.id, external_id="sd-parent"
    )
    product_repo.create_channel_mapping(
        channel="sevdesk", entity_type="product", internal_entity_id=child.id, external_id="sd-child"
    )

    preview = grouping.preview_grouping(parent_product_id=parent.id, child_product_ids=[child.id])

    assert preview.is_safe is False
    assert len(preview.channel_mapping_conflicts) == 1
    refreshed_child = product_repo.get_product(child.id)
    assert refreshed_child is not None and refreshed_child.active is True


def test_preview_grouping_counts_movable_rows(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, _ = product_repo.create_product(sku="XW-800", name="Parent")
    child, _ = product_repo.create_product(sku="XW-800.1", name="Child")
    product_repo.add_identifier(
        product_id=child.id, scheme="ASIN", value="A1", normalized_value="A1"
    )

    preview = grouping.preview_grouping(parent_product_id=parent.id, child_product_ids=[child.id])

    assert preview.is_safe is True
    assert preview.variants_to_move == 1
    assert preview.identifiers_to_move == 1


def test_group_products_into_parent_rejects_parent_as_its_own_child(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, _ = product_repo.create_product(sku="XW-900", name="Parent")
    with pytest.raises(ValueError, match="must not also be"):
        grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[parent.id])


def test_group_products_into_parent_rejects_empty_children(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, _ = product_repo.create_product(sku="XW-901", name="Parent")
    with pytest.raises(ValueError, match="must not be empty"):
        grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[])


def test_group_products_into_parent_unknown_child_aborts_without_partial_writes(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, _ = product_repo.create_product(sku="XW-902", name="Parent")
    real_child, real_child_variant = product_repo.create_product(sku="XW-902.1", name="Echtes Kind")
    fake_child_id = uuid.uuid4()

    with pytest.raises(KeyError):
        grouping.group_products_into_parent(
            parent_product_id=parent.id, child_product_ids=[real_child.id, fake_child_id]
        )

    # The real child must not have been half-processed before the unknown one failed.
    refreshed_variant = product_repo.get_variant(real_child_variant.id)
    assert refreshed_variant is not None
    assert refreshed_variant.product_id == real_child.id
    refreshed_child = product_repo.get_product(real_child.id)
    assert refreshed_child is not None and refreshed_child.active is True
