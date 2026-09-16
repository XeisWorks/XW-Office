"""Tests for the XW Product Hub import staging schema (PR02): models + repository."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub_import import StagingProduct
from xw_office.repositories.product_hub_import import (
    ProductHubImportRepository,
    StagingProductFilter,
    hash_payload,
)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def repo(session_factory: sessionmaker[Session]) -> ProductHubImportRepository:
    return ProductHubImportRepository(session_factory)


def test_create_batch_and_ingest_staging_product(repo: ProductHubImportRepository) -> None:
    batch = repo.create_batch(source="wix", source_metadata={"catalog_version": "v3"})
    assert batch.status == "running"

    staged = repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="wix",
        source_key="wix-product-1",
        raw_payload={"id": "wix-product-1", "name": "Ohrwürmer #1"},
        sku="XW-001",
        name="Ohrwürmer #1",
    )

    assert staged.import_batch_id == batch.id
    assert staged.match_status == "unmatched"
    assert staged.payload_hash == hash_payload(staged.raw_payload)


def test_ingest_same_source_key_twice_does_not_duplicate(
    repo: ProductHubImportRepository,
) -> None:
    batch = repo.create_batch(source="sevdesk")
    payload = {"id": "part-42", "name": "Test Part"}

    first = repo.ingest_staging_product(
        import_batch_id=batch.id, source="sevdesk", source_key="part-42", raw_payload=payload
    )
    second = repo.ingest_staging_product(
        import_batch_id=batch.id, source="sevdesk", source_key="part-42", raw_payload=payload
    )

    assert first.id == second.id
    rows = repo.list_staging_products(StagingProductFilter(import_batch_id=batch.id))
    assert len(rows) == 1


def test_ingest_updated_payload_changes_hash_without_new_row(
    repo: ProductHubImportRepository,
) -> None:
    batch = repo.create_batch(source="sevdesk")
    repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="sevdesk",
        source_key="part-99",
        raw_payload={"name": "Old Name"},
    )
    updated = repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="sevdesk",
        source_key="part-99",
        raw_payload={"name": "New Name"},
    )

    rows = repo.list_staging_products(StagingProductFilter(import_batch_id=batch.id))
    assert len(rows) == 1
    assert updated.raw_payload["name"] == "New Name"
    assert updated.payload_hash == hash_payload({"name": "New Name"})


def test_hash_payload_is_stable_regardless_of_key_order() -> None:
    a = hash_payload({"a": 1, "b": 2})
    b = hash_payload({"b": 2, "a": 1})
    assert a == b


def test_ingest_preserves_existing_match_decision(repo: ProductHubImportRepository) -> None:
    batch = repo.create_batch(source="wix")
    staged = repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="wix",
        source_key="wix-1",
        raw_payload={"name": "V1"},
    )
    fake_product_id = uuid.uuid4()
    repo.set_match(
        staged.id,
        match_status="approved",
        proposed_product_id=fake_product_id,
        match_method="exact_sku",
        match_score=1.0,
    )

    refreshed = repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="wix",
        source_key="wix-1",
        raw_payload={"name": "V2 — refetched"},
    )

    assert refreshed.match_status == "approved"
    assert refreshed.proposed_product_id == fake_product_id


def test_finish_batch_marks_completed(repo: ProductHubImportRepository) -> None:
    batch = repo.create_batch(source="excel")
    finished = repo.finish_batch(batch.id, status="completed")
    assert finished.status == "completed"
    assert finished.finished_at is not None


def test_finish_batch_records_error_summary(repo: ProductHubImportRepository) -> None:
    batch = repo.create_batch(source="excel")
    finished = repo.finish_batch(batch.id, status="failed", error_summary="sheet not found")
    assert finished.status == "failed"
    assert finished.error_summary == "sheet not found"


def test_list_staging_products_filters_by_match_status(
    repo: ProductHubImportRepository,
) -> None:
    batch = repo.create_batch(source="excel")
    a = repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="row-1", raw_payload={"sku": "A"}
    )
    repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="row-2", raw_payload={"sku": "B"}
    )
    repo.set_match(a.id, match_status="approved")

    approved = repo.list_staging_products(
        StagingProductFilter(import_batch_id=batch.id, match_status="approved")
    )
    assert [row.id for row in approved] == [a.id]

    unmatched = repo.list_staging_products(
        StagingProductFilter(import_batch_id=batch.id, match_status="unmatched")
    )
    assert len(unmatched) == 1


def test_staging_sub_rows_round_trip(repo: ProductHubImportRepository) -> None:
    batch = repo.create_batch(source="wix")
    staged = repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="wix",
        source_key="wix-2",
        raw_payload={"name": "Book"},
    )
    repo.add_identifier(
        staged.id, scheme="ISBN13", value="978-3-16-148410-0", normalized_value="9783161484100"
    )
    repo.add_asset(staged.id, role="COVER", source_url="https://example.invalid/cover.jpg")
    repo.add_inventory(staged.id, quantity=12, location_external_id="loc-1")
    repo.add_category(staged.id, external_category_id="cat-1", external_category_name="Books")
    repo.add_variant(staged.id, sku="XW-2-A", name="Variant A")
    repo.add_match_candidate(
        staged.id, candidate_product_id=uuid.uuid4(), match_method="fuzzy_suggested", rank=1
    )

    assert len(repo.list_identifiers(staged.id)) == 1
    assert len(repo.list_variants(staged.id)) == 1
    assert len(repo.list_match_candidates(staged.id)) == 1


def test_rollback_on_error_leaves_no_partial_staging_rows(
    session_factory: sessionmaker[Session],
) -> None:
    """A mid-transaction failure must not leave a partially-ingested batch behind."""
    with session_factory() as session:
        repo = ProductHubImportRepository(session)
        batch = repo.create_batch(source="wix")
        repo.ingest_staging_product(
            import_batch_id=batch.id,
            source="wix",
            source_key="dup-key",
            raw_payload={"name": "First"},
        )
        # Force a constraint violation within the same still-open transaction: a second
        # row with the same (batch, source, source_key) violates the unique constraint
        # that ``ingest_staging_product`` normally avoids by upserting.
        session.add(
            StagingProduct(
                id=uuid.uuid4(),
                import_batch_id=batch.id,
                source="wix",
                source_key="dup-key",
                raw_payload={"name": "Conflicting duplicate"},
                payload_hash=hash_payload({"name": "Conflicting duplicate"}),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with session_factory() as verify_session:
        remaining = verify_session.scalars(select(StagingProduct)).all()
        assert remaining == []
