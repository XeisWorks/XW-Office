"""Tests for the Import Commit Service (PR06)."""
from __future__ import annotations

from decimal import Decimal
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList, ProductIdentifier
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_import import ProductHubImportRepository
from xw_office.services.product_hub.import_commit import CommitError, ImportCommitService


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def product_repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


@pytest.fixture
def import_repo(session_factory: sessionmaker[Session]) -> ProductHubImportRepository:
    return ProductHubImportRepository(session_factory)


@pytest.fixture
def commit_service(session_factory: sessionmaker[Session]) -> ImportCommitService:
    return ImportCommitService(session_factory)


# -- create_from_staging --------------------------------------------------------------


def test_create_from_staging_creates_product_with_identifiers_and_tags(
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="XW-777",
        sku="XW-777",
        name="Nur bei Amazon",
        raw_payload={},
        normalized_fields={"suggested_tags": ["Amazon"]},
    )
    import_repo.add_identifier(staged.id, scheme="ASIN", value="A1", normalized_value="A1")

    product = commit_service.create_from_staging(staged.id, actor="tester")

    assert product.sku == "XW-777"
    variants = product_repo.list_variants(product.id)
    assert len(variants) == 1 and variants[0].is_default is True

    identifiers = product_repo.list_identifiers(product_id=product.id)
    assert {row.scheme for row in identifiers} == {"ASIN"}

    tags = product_repo.list_product_tags(product.id)
    assert len(tags) == 1

    refreshed_staging = import_repo.get_staging_product(staged.id)
    assert refreshed_staging is not None
    assert refreshed_staging.match_status == "committed"
    assert refreshed_staging.committed_product_id == product.id

    audit = product_repo.list_audit_log("product", product.id)
    assert any(entry.action == "create_from_staging" for entry in audit)


def test_create_from_staging_is_idempotent(
    import_repo: ProductHubImportRepository, commit_service: ImportCommitService
) -> None:
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="XW-778", sku="XW-778", name="X", raw_payload={}
    )

    first = commit_service.create_from_staging(staged.id)
    second = commit_service.create_from_staging(staged.id)

    assert first.id == second.id


def test_create_from_staging_rejects_non_creatable_status(
    import_repo: ProductHubImportRepository, commit_service: ImportCommitService
) -> None:
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="XW-779", sku="XW-779", name="X", raw_payload={}
    )
    import_repo.set_match(staged.id, match_status="suggested_match", match_score=0.9)

    with pytest.raises(CommitError):
        commit_service.create_from_staging(staged.id)


def test_create_from_staging_requires_sku(
    import_repo: ProductHubImportRepository, commit_service: ImportCommitService
) -> None:
    batch = import_repo.create_batch(source="sevdesk")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="sevdesk", source_key="503", name="Ohne SKU", raw_payload={}
    )

    with pytest.raises(CommitError):
        commit_service.create_from_staging(staged.id)


def test_create_from_staging_merges_wix_channel_mapping_and_excel_category(
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="XW-101",
        sku="XW-101",
        name="Ohrwürmer #1",
        raw_payload={},
    )
    import_repo.add_category(
        staged.id, external_category_id="tanzlmusi-edition", external_category_name="TANZLMUSI EDITION"
    )

    product = commit_service.create_from_staging(staged.id)

    categories = product_repo.list_product_categories(product.id)
    assert len(categories) == 1


def test_create_from_staging_creates_channel_mapping_for_wix_source(
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    batch = import_repo.create_batch(source="wix")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="wix",
        source_key="wix-1",
        source_external_id="wix-1",
        sku="XW-800",
        name="Wix Produkt",
        raw_payload={},
    )

    product = commit_service.create_from_staging(staged.id)

    mapping = product_repo.get_channel_mapping(channel="wix", entity_type="product", external_id="wix-1")
    assert mapping is not None
    assert mapping.internal_entity_id == product.id


# -- approve_match / reject_match -----------------------------------------------------


def test_approve_match_requires_exact_or_suggested_status(
    import_repo: ProductHubImportRepository, commit_service: ImportCommitService
) -> None:
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="a", sku="XW-1", name="x", raw_payload={}
    )

    with pytest.raises(CommitError):
        commit_service.approve_match(staged.id)


def test_approve_match_preserves_proposed_product(
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    commit_service: ImportCommitService,
) -> None:
    target, _ = product_repo.create_product(sku="XW-2", name="Ziel")
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="a", sku="OTHER", name="x", raw_payload={}
    )
    import_repo.set_match(
        staged.id, match_status="exact_match", proposed_product_id=target.id, match_method="exact_sku", match_score=1.0
    )

    updated = commit_service.approve_match(staged.id, actor="reviewer")

    assert updated.match_status == "approved"
    assert updated.proposed_product_id == target.id


def test_reject_match_records_note(
    import_repo: ProductHubImportRepository, commit_service: ImportCommitService
) -> None:
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="a", sku="XW-3", name="x", raw_payload={}
    )

    updated = commit_service.reject_match(staged.id, note="falscher Vorschlag")

    assert updated.match_status == "rejected"
    assert updated.decision_note == "falscher Vorschlag"


# -- commit_approved_match --------------------------------------------------------------


def test_commit_approved_match_links_and_enriches_existing_product(
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    commit_service: ImportCommitService,
) -> None:
    target, _ = product_repo.create_product(sku="XW-4", name="Bestehend")
    batch = import_repo.create_batch(source="sevdesk")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="sevdesk",
        source_key="part-1",
        source_external_id="part-1",
        sku="XW-4",
        name="Bestehend",
        raw_payload={},
    )
    import_repo.set_match(
        staged.id, match_status="approved", proposed_product_id=target.id, match_method="exact_sku", match_score=1.0
    )

    committed = commit_service.commit_approved_match(staged.id)

    assert committed.id == target.id
    mapping = product_repo.get_channel_mapping(channel="sevdesk", entity_type="product", external_id="part-1")
    assert mapping is not None and mapping.internal_entity_id == target.id


def test_commit_approved_match_requires_approved_status(
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    commit_service: ImportCommitService,
) -> None:
    target, _ = product_repo.create_product(sku="XW-5", name="X")
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="a", sku="XW-5", name="x", raw_payload={}
    )
    import_repo.set_match(staged.id, match_status="exact_match", proposed_product_id=target.id)

    with pytest.raises(CommitError):
        commit_service.commit_approved_match(staged.id)


def test_commit_approved_match_is_idempotent(
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    commit_service: ImportCommitService,
) -> None:
    target, _ = product_repo.create_product(sku="XW-6", name="X")
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="a", sku="XW-6", name="x", raw_payload={}
    )
    import_repo.set_match(staged.id, match_status="approved", proposed_product_id=target.id)

    first = commit_service.commit_approved_match(staged.id)
    second = commit_service.commit_approved_match(staged.id)

    assert first.id == second.id == target.id


# -- identifier conflicts --------------------------------------------------------------


def test_identifier_conflict_raises_and_commits_nothing(
    session_factory: sessionmaker[Session],
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    commit_service: ImportCommitService,
) -> None:
    owner, _ = product_repo.create_product(sku="XW-7", name="Original")
    with session_factory() as session:
        session.add(
            ProductIdentifier(
                id=uuid.uuid4(), product_id=owner.id, scheme="ASIN", value="A9", normalized_value="A9"
            )
        )
        session.commit()

    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="XW-8", sku="XW-8", name="Anderes Produkt", raw_payload={}
    )
    import_repo.add_identifier(staged.id, scheme="ASIN", value="A9", normalized_value="A9")

    with pytest.raises(CommitError):
        commit_service.create_from_staging(staged.id)

    refreshed = import_repo.get_staging_product(staged.id)
    assert refreshed is not None
    assert refreshed.committed_product_id is None
    assert refreshed.match_status == "unmatched"  # unchanged - nothing was committed
    assert product_repo.get_product_by_sku("XW-8") is None


# -- commit_import_batch -----------------------------------------------------------------


def test_commit_import_batch_creates_unmatched_and_links_approved(
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    commit_service: ImportCommitService,
) -> None:
    existing, _ = product_repo.create_product(sku="XW-EXIST", name="Existiert schon")
    batch = import_repo.create_batch(source="excel")

    import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="new-1", sku="XW-NEW-1", name="Neu 1", raw_payload={}
    )
    approved = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="lnk-1", sku="XW-LNK-1", name="Link", raw_payload={}
    )
    import_repo.set_match(approved.id, match_status="approved", proposed_product_id=existing.id)
    suggested = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="sug-1", sku="XW-SUG-1", name="Vorschlag", raw_payload={}
    )
    import_repo.set_match(suggested.id, match_status="suggested_match", match_score=0.85)

    report = commit_service.commit_import_batch(batch.id)

    assert report.created == 1
    assert report.linked == 1
    assert report.skipped_needs_review == 1
    assert report.errors == []


def test_commit_import_batch_is_idempotent_on_rerun(
    import_repo: ProductHubImportRepository, commit_service: ImportCommitService
) -> None:
    batch = import_repo.create_batch(source="excel")
    import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="a", sku="XW-REPEAT", name="X", raw_payload={}
    )

    first = commit_service.commit_import_batch(batch.id)
    second = commit_service.commit_import_batch(batch.id)

    assert first.created == 1
    assert second.created == 0
    assert second.already_committed == 1


def test_commit_import_batch_reports_conflict_without_aborting_other_rows(
    session_factory: sessionmaker[Session],
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    commit_service: ImportCommitService,
) -> None:
    owner, _ = product_repo.create_product(sku="XW-OWNER", name="Original")
    with session_factory() as session:
        session.add(
            ProductIdentifier(
                id=uuid.uuid4(), product_id=owner.id, scheme="ASIN", value="A5", normalized_value="A5"
            )
        )
        session.commit()

    batch = import_repo.create_batch(source="excel")
    bad = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="bad", sku="XW-BAD", name="Konflikt", raw_payload={}
    )
    import_repo.add_identifier(bad.id, scheme="ASIN", value="A5", normalized_value="A5")
    import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="good", sku="XW-GOOD", name="Ok", raw_payload={}
    )

    report = commit_service.commit_import_batch(batch.id)

    assert report.created == 1
    assert len(report.errors) == 1
    assert "XW-BAD" in report.errors[0] or "bad" in report.errors[0]


# -- preview_commit -----------------------------------------------------------------------


def test_preview_commit_shows_create_action_for_unmatched(
    import_repo: ProductHubImportRepository, commit_service: ImportCommitService
) -> None:
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="a", sku="XW-9", name="x", raw_payload={}
    )

    preview = commit_service.preview_commit(staged.id)

    assert preview.action == "create"
    assert preview.target_product_id is None


def test_preview_commit_shows_blocked_for_suggested_match(
    import_repo: ProductHubImportRepository, commit_service: ImportCommitService
) -> None:
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="a", sku="XW-10", name="x", raw_payload={}
    )
    import_repo.set_match(staged.id, match_status="suggested_match", match_score=0.85)

    preview = commit_service.preview_commit(staged.id)

    assert preview.action == "blocked"
    assert preview.blocked_reason is not None


def test_preview_commit_shows_already_committed(
    import_repo: ProductHubImportRepository, commit_service: ImportCommitService
) -> None:
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id, source="excel", source_key="a", sku="XW-11", name="x", raw_payload={}
    )
    commit_service.create_from_staging(staged.id)

    preview = commit_service.preview_commit(staged.id)

    assert preview.action == "already_committed"
    assert preview.target_product_id is not None


# -- price merge on commit (2026-09-17: deterministic 10% VAT unblocked this) ----------


def test_create_from_staging_sets_retail_price_from_excel_brutto_netto(
    session_factory: sessionmaker[Session],
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    with session_factory() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.commit()

    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="XW-500",
        sku="XW-500",
        name="Preisprodukt",
        raw_payload={},
        normalized_fields={"brutto": "42.90", "netto": "39.00", "tax_rate": "0.10"},
    )

    product = commit_service.create_from_staging(staged.id)

    variant = product_repo.get_default_variant(product.id)
    assert variant is not None
    prices = product_repo.list_prices(variant.id)
    assert len(prices) == 1
    assert prices[0].gross_amount == Decimal("42.90")
    assert prices[0].net_amount == Decimal("39.00")
    assert prices[0].tax_rate == Decimal("0.10")


def test_create_from_staging_without_price_list_skips_price_gracefully(
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    # No RETAIL_EUR price list seeded — must not raise, just skip pricing.
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="XW-501",
        sku="XW-501",
        name="Kein Preislistenprodukt",
        raw_payload={},
        normalized_fields={"brutto": "10.00", "netto": "9.09", "tax_rate": "0.10"},
    )

    product = commit_service.create_from_staging(staged.id)

    variant = product_repo.get_default_variant(product.id)
    assert variant is not None
    assert product_repo.list_prices(variant.id) == []


def test_create_from_staging_price_merge_is_idempotent(
    session_factory: sessionmaker[Session],
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    with session_factory() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.commit()

    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="XW-502",
        sku="XW-502",
        name="Idempotenzprodukt",
        raw_payload={},
        normalized_fields={"brutto": "20.00", "netto": "18.18", "tax_rate": "0.10"},
    )

    product = commit_service.create_from_staging(staged.id)
    commit_service.create_from_staging(staged.id)  # idempotent re-call

    variant = product_repo.get_default_variant(product.id)
    assert variant is not None
    assert len(product_repo.list_prices(variant.id)) == 1
