"""Tests for the cross-source matching engine (PR05 continued)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import ChannelMapping, ProductIdentifier, ProductSkuAlias
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_import import ProductHubImportRepository
from xw_office.services.product_hub.matching import MatchingEngine


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
def engine(
    product_repo: ProductHubRepository, import_repo: ProductHubImportRepository
) -> MatchingEngine:
    return MatchingEngine(import_repo=import_repo, product_repo=product_repo)


def test_matches_via_existing_channel_mapping(
    session_factory: sessionmaker[Session],
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    engine: MatchingEngine,
) -> None:
    product, _ = product_repo.create_product(sku="XW-100", name="Kanonisch")
    with session_factory() as session:
        session.add(
            ChannelMapping(
                id=uuid.uuid4(),
                channel="wix",
                entity_type="product",
                internal_entity_id=product.id,
                external_id="wix-abc",
                sync_status="synced",
            )
        )
        session.commit()

    batch = import_repo.create_batch(source="wix")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="wix",
        source_key="wix-abc",
        source_external_id="wix-abc",
        sku="DIFFERENT-SKU-ON-WIX",
        name="Anderer Name auf Wix",
        raw_payload={},
    )

    report = engine.run(batch_id=batch.id)

    assert report.exact_external_id == 1
    refreshed = import_repo.get_staging_product(staged.id)
    assert refreshed is not None
    assert refreshed.match_status == "exact_match"
    assert refreshed.match_method == "existing_external_id"
    assert refreshed.proposed_product_id == product.id


def test_matches_via_exact_sku(
    product_repo: ProductHubRepository, import_repo: ProductHubImportRepository, engine: MatchingEngine
) -> None:
    product, _ = product_repo.create_product(sku="XW-200", name="Produkt 200")
    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="XW-200",
        sku="xw-200",
        name="Produkt 200",
        raw_payload={},
    )

    report = engine.run(batch_id=batch.id)

    assert report.exact_sku == 1
    refreshed = import_repo.get_staging_product(staged.id)
    assert refreshed is not None
    assert refreshed.match_status == "exact_match"
    assert refreshed.match_method == "exact_sku"
    assert refreshed.proposed_product_id == product.id


def test_matches_via_sku_alias(
    session_factory: sessionmaker[Session],
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    engine: MatchingEngine,
) -> None:
    product, variant = product_repo.create_product(sku="XW-300", name="Produkt 300")
    with session_factory() as session:
        session.add(
            ProductSkuAlias(
                product_id=product.id, alias_sku="LEGACY-300", source="legacy", variant_id=variant.id
            )
        )
        session.commit()

    batch = import_repo.create_batch(source="excel")
    import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="LEGACY-300",
        sku="legacy-300",
        name="Produkt 300",
        raw_payload={},
    )

    report = engine.run(batch_id=batch.id)

    assert report.alias_sku == 1
    staged = import_repo.list_staging_products()[0]
    assert staged.match_method == "sku_alias"
    assert staged.proposed_product_id == product.id


def test_matches_via_identifier(
    session_factory: sessionmaker[Session],
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    engine: MatchingEngine,
) -> None:
    product, _ = product_repo.create_product(sku="XW-400", name="Buch 400")
    with session_factory() as session:
        session.add(
            ProductIdentifier(
                id=uuid.uuid4(),
                product_id=product.id,
                scheme="ISBN13",
                value="9783161484100",
                normalized_value="9783161484100",
            )
        )
        session.commit()

    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="AMAZON-ONLY-SKU",
        sku="AMAZON-ONLY-SKU",  # deliberately does not match product.sku
        name="Buch 400 (Amazon)",
        raw_payload={},
    )
    import_repo.add_identifier(
        staged.id, scheme="ISBN13", value="9783161484100", normalized_value="9783161484100"
    )

    report = engine.run(batch_id=batch.id)

    assert report.identifier_matches == 1
    refreshed = import_repo.get_staging_product(staged.id)
    assert refreshed is not None
    assert refreshed.match_method == "identifier"
    assert refreshed.proposed_product_id == product.id


def test_identifier_conflict_is_flagged_not_merged(
    session_factory: sessionmaker[Session],
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    engine: MatchingEngine,
) -> None:
    """A conflict is a staged row whose *own* identifiers disagree with each other
    (e.g. its ASIN resolves to one existing product, its ISBN to a different one) —
    a genuine data contradiction the engine must surface, not silently resolve."""
    product_a, _ = product_repo.create_product(sku="XW-500", name="Produkt A")
    product_b, _ = product_repo.create_product(sku="XW-501", name="Produkt B")
    with session_factory() as session:
        session.add_all(
            [
                ProductIdentifier(
                    id=uuid.uuid4(),
                    product_id=product_a.id,
                    scheme="ASIN",
                    value="A0000000A",
                    normalized_value="A0000000A",
                ),
                ProductIdentifier(
                    id=uuid.uuid4(),
                    product_id=product_b.id,
                    scheme="ISBN13",
                    value="9780000000000",
                    normalized_value="9780000000000",
                ),
            ]
        )
        session.commit()

    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="XW-999",
        sku="XW-999",
        name="Widersprüchliches Produkt",
        raw_payload={},
    )
    import_repo.add_identifier(staged.id, scheme="ASIN", value="A0000000A", normalized_value="A0000000A")
    import_repo.add_identifier(
        staged.id, scheme="ISBN13", value="9780000000000", normalized_value="9780000000000"
    )

    report = engine.run(batch_id=batch.id)

    assert report.conflicts, "contradictory identifiers on one staged row must be flagged"
    refreshed = import_repo.get_staging_product(staged.id)
    assert refreshed is not None
    assert refreshed.match_status == "conflict"
    assert refreshed.proposed_product_id is None


def test_single_identifier_reuse_is_a_normal_match_not_a_conflict(
    session_factory: sessionmaker[Session],
    product_repo: ProductHubRepository,
    import_repo: ProductHubImportRepository,
    engine: MatchingEngine,
) -> None:
    """One staged identifier matching one existing product is a legitimate tier-4
    match (e.g. an Excel-only SKU that is really the same item under a legacy code) —
    not a conflict just because the SKU itself does not also match."""
    owner_product, _ = product_repo.create_product(sku="XW-500", name="Original")
    with session_factory() as session:
        session.add(
            ProductIdentifier(
                id=uuid.uuid4(),
                product_id=owner_product.id,
                scheme="ASIN",
                value="B000000000",
                normalized_value="B000000000",
            )
        )
        session.commit()

    batch = import_repo.create_batch(source="excel")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="XW-999",
        sku="XW-999",
        name="Original",
        raw_payload={},
    )
    import_repo.add_identifier(staged.id, scheme="ASIN", value="B000000000", normalized_value="B000000000")

    report = engine.run(batch_id=batch.id)

    assert report.conflicts == []
    assert report.identifier_matches == 1
    refreshed = import_repo.get_staging_product(staged.id)
    assert refreshed is not None
    assert refreshed.match_status == "exact_match"
    assert refreshed.proposed_product_id == owner_product.id


def test_fuzzy_suggestion_never_auto_applies(
    product_repo: ProductHubRepository, import_repo: ProductHubImportRepository, engine: MatchingEngine
) -> None:
    product, _ = product_repo.create_product(sku="XW-600", name="Ohrwürmer #1 TRP")
    batch = import_repo.create_batch(source="wix")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="wix",
        source_key="wix-fuzzy-1",
        sku="COMPLETELY-DIFFERENT-SKU",
        name="Ohrwürmer #1 Trompete",  # similar but not identical name
        raw_payload={},
    )

    report = engine.run(batch_id=batch.id)

    assert report.suggested_matches == 1
    refreshed = import_repo.get_staging_product(staged.id)
    assert refreshed is not None
    assert refreshed.match_status == "suggested_match"
    # Never "approved"/"exact_match" — a human must confirm a fuzzy suggestion.
    assert refreshed.match_status not in {"approved", "exact_match", "committed"}
    assert refreshed.proposed_product_id is None

    candidates = import_repo.list_match_candidates(staged.id)
    assert len(candidates) == 1
    assert candidates[0].candidate_product_id == product.id
    assert candidates[0].match_method == "fuzzy_suggested"


def test_no_fuzzy_suggestion_below_threshold_stays_unmatched(
    product_repo: ProductHubRepository, import_repo: ProductHubImportRepository, engine: MatchingEngine
) -> None:
    product_repo.create_product(sku="XW-700", name="Völlig anderer Titel")
    batch = import_repo.create_batch(source="wix")
    staged = import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="wix",
        source_key="wix-nomatch",
        sku="NO-MATCH-SKU",
        name="Ganz unähnlicher Name xyz123",
        raw_payload={},
    )

    report = engine.run(batch_id=batch.id)

    assert report.unmatched == 1
    assert report.suggested_matches == 0
    refreshed = import_repo.get_staging_product(staged.id)
    assert refreshed is not None
    assert refreshed.match_status == "unmatched"


def test_duplicate_claims_are_reported(
    product_repo: ProductHubRepository, import_repo: ProductHubImportRepository, engine: MatchingEngine
) -> None:
    product_repo.create_product(sku="XW-800", name="Geteiltes Produkt")
    batch = import_repo.create_batch(source="excel")
    import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="row-a",
        sku="XW-800",
        name="Geteiltes Produkt (A)",
        raw_payload={},
    )
    import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="row-b",
        sku="xw-800",
        name="Geteiltes Produkt (B)",
        raw_payload={},
    )

    report = engine.run(batch_id=batch.id)

    assert report.exact_sku == 2
    assert len(report.duplicates) == 1


def test_title_drift_is_reported_on_sku_match_with_different_name(
    product_repo: ProductHubRepository, import_repo: ProductHubImportRepository, engine: MatchingEngine
) -> None:
    product_repo.create_product(sku="XW-900", name="Kanonischer Titel Original")
    batch = import_repo.create_batch(source="excel")
    import_repo.ingest_staging_product(
        import_batch_id=batch.id,
        source="excel",
        source_key="XW-900",
        sku="XW-900",
        name="Ganz anders benannter Titel 123",
        raw_payload={},
    )

    report = engine.run(batch_id=batch.id)

    assert report.exact_sku == 1
    assert len(report.title_drift) == 1


def test_run_without_batch_id_matches_across_all_staging(
    product_repo: ProductHubRepository, import_repo: ProductHubImportRepository, engine: MatchingEngine
) -> None:
    product_repo.create_product(sku="XW-1000", name="Produkt 1000")
    batch_one = import_repo.create_batch(source="wix")
    import_repo.ingest_staging_product(
        import_batch_id=batch_one.id, source="wix", source_key="a", sku="XW-1000", name="x", raw_payload={}
    )
    batch_two = import_repo.create_batch(source="excel")
    import_repo.ingest_staging_product(
        import_batch_id=batch_two.id, source="excel", source_key="b", sku="does-not-exist", name="y", raw_payload={}
    )

    report = engine.run()

    assert report.rows_considered == 2
    assert report.exact_sku == 1
    assert report.unmatched == 1
