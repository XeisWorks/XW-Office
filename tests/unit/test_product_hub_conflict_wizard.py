from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import Product, ProductVariant
from xw_office.models.product_hub_conflicts import ConflictAction
from xw_office.models.product_hub_sync import OutboxEvent
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.conflicts.normalizer import equivalent, normalize_value
from xw_office.services.product_hub.conflicts.service import (
    ConflictWizardService,
    StaleConflictError,
)
from xw_office.web import ContentWebSettings, create_app


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'conflicts.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _seed(
    factory: sessionmaker[Session], *, hub: object = "Hub title", external: object = "Wix title"
) -> tuple[Product, ConflictWizardService]:
    product, _ = ProductHubRepository(factory).create_product(sku="XW-CW-1", name=str(hub))
    SyncRepository(factory).create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        field_name="name",
        hub_value=hub,
        external_value=external,
    )
    return product, ConflictWizardService(factory)


def test_normalizer_suppresses_non_semantic_differences() -> None:
    assert equivalent("title", "  [PRINT] Tuba in Bb  ", "TUBA in B")
    assert normalize_value("price_gross", "9,9") == "9.90"


def test_repeated_scan_updates_one_case(factory: sessionmaker[Session]) -> None:
    _, service = _seed(factory)
    first = service.scan_low_level_conflicts()
    second = service.scan_low_level_conflicts()
    rows, total = service.repository.list_cases()
    assert first["cases_created"] == 1
    assert second["cases_created"] == 0
    assert second["cases_updated"] == 1
    assert total == 1
    assert len(rows) == 1


def test_known_sku_alias_does_not_create_conflict(factory: sessionmaker[Session]) -> None:
    products = ProductHubRepository(factory)
    product, variant = products.create_product(sku="XW-4043", name="Alias product")
    products.add_sku_alias(
        product.id, alias_sku="XW-443", variant_id=variant.id, source="test"
    )
    SyncRepository(factory).create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        field_name="sku",
        hub_value="XW-4043",
        external_value="XW-443",
    )
    result = ConflictWizardService(factory).scan_low_level_conflicts()
    assert result["differences_found"] == 0


def test_decision_preview_and_hub_apply_are_audited(factory: sessionmaker[Session]) -> None:
    product, service = _seed(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]
    decided = service.decide(
        case.id, expected_row_version=case.row_version, resolution_type="USE_WIX"
    )
    actions = service.preview(case.id)
    assert [(row.channel, row.action_type) for row in actions] == [("hub", "UPDATE_FIELD")]
    applied = service.apply(
        case.id, expected_row_version=decided.row_version, channel_apply_enabled=False
    )
    assert applied.status == "RESOLVED"
    with factory() as session:
        refreshed = session.get(Product, product.id)
        assert refreshed is not None and refreshed.name == "Wix title"
        assert session.query(Product).count() == 1
        assert session.execute(text("select count(*) from audit_log")).scalar_one() == 1


def test_use_wix_visible_value_is_stored_as_boolean(factory: sessionmaker[Session]) -> None:
    product, _ = ProductHubRepository(factory).create_product(sku="XW-CW-VISIBLE", name="Sichtbar")
    SyncRepository(factory).create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        field_name="visible",
        hub_value=True,
        external_value="false",
    )
    service = ConflictWizardService(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]

    decided = service.decide(
        case.id, expected_row_version=case.row_version, resolution_type="USE_WIX"
    )
    service.preview(case.id)
    applied = service.apply(
        case.id, expected_row_version=decided.row_version, channel_apply_enabled=False
    )

    assert applied.status == "RESOLVED"
    with factory() as session:
        refreshed = session.get(Product, product.id)
        assert refreshed is not None
        assert refreshed.active is False


def test_intentional_difference_is_not_reopened(factory: sessionmaker[Session]) -> None:
    _, service = _seed(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]
    resolved = service.decide(
        case.id, expected_row_version=case.row_version, resolution_type="INTENTIONAL_DIFFERENCE"
    )
    assert resolved.status == "RESOLVED"
    result = service.scan_low_level_conflicts()
    assert result["cases_created"] == 0


def test_stale_product_blocks_apply(factory: sessionmaker[Session]) -> None:
    product, service = _seed(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]
    decided = service.decide(
        case.id, expected_row_version=case.row_version, resolution_type="USE_WIX"
    )
    service.preview(case.id)
    with factory.begin() as session:
        row = session.get(Product, product.id)
        assert row is not None
        row.row_version += 1
    with pytest.raises(StaleConflictError):
        service.apply(
            case.id, expected_row_version=decided.row_version, channel_apply_enabled=False
        )


def test_wix_apply_is_queued_and_only_readback_completion_resolves(
    factory: sessionmaker[Session],
) -> None:
    _, service = _seed(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]
    decided = service.decide(
        case.id, expected_row_version=case.row_version, resolution_type="USE_HUB"
    )
    actions = service.preview(case.id)
    assert len(actions) == 1 and actions[0].channel == "wix"
    queued = service.apply(
        case.id,
        expected_row_version=decided.row_version,
        channel_apply_enabled=True,
    )
    assert queued.status == "PARTIALLY_RESOLVED"
    with factory() as session:
        event = session.query(OutboxEvent).filter_by(event_type="conflict.wix_apply").one()
        action = session.get(ConflictAction, actions[0].id)
        assert action is not None and action.status == "QUEUED"
    service.finish_wix_action(event)
    assert service.repository.get_case(case.id).status == "RESOLVED"  # type: ignore[union-attr]


def test_mapping_candidate_can_be_applied_with_audited_remap(factory: sessionmaker[Session]) -> None:
    products = ProductHubRepository(factory)
    product, _variant = products.create_product(sku="XW-MAP-1", name="Mapped product")
    mapping = products.create_channel_mapping(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        external_id="old-wix-id",
    )
    low = SyncRepository(factory).create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        field_name="mapping",
        hub_value={"state": "mapped", "external_id": mapping.external_id},
        external_value={"state": "not_found", "external_id": mapping.external_id},
    )
    service = ConflictWizardService(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]

    resolved = service.remap_wix_mapping(
        case.id,
        expected_row_version=case.row_version,
        external_id="replacement-wix-id",
        note="Kandidat aus Wix-Suche bestätigt",
    )

    assert resolved.status == "RESOLVED"
    assert resolved.resolution_type == "REMAP_WIX"
    with factory() as session:
        refreshed = session.get(type(mapping), mapping.id)
        assert refreshed is not None and refreshed.external_id == "replacement-wix-id"
        refreshed_low = session.get(type(low), low.id)
        assert refreshed_low is not None and refreshed_low.resolution == "mapping_reassigned"
        assert session.execute(text("select count(*) from audit_log")).scalar_one() == 1


def test_remap_rejects_existing_wix_id_with_legacy_prefix(factory: sessionmaker[Session]) -> None:
    products = ProductHubRepository(factory)
    target, _ = products.create_product(sku="XW-MAP-TARGET", name="Target")
    other, _ = products.create_product(sku="XW-MAP-OTHER", name="Other")
    mapping = products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=target.id, external_id="old-id"
    )
    products.create_channel_mapping(
        channel="wix",
        entity_type="product",
        internal_entity_id=other.id,
        external_id="product_replacement-id",
    )
    SyncRepository(factory).create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=target.id,
        field_name="mapping",
        hub_value={"state": "mapped", "external_id": mapping.external_id},
        external_value={"state": "not_found", "external_id": mapping.external_id},
    )
    service = ConflictWizardService(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]

    with pytest.raises(ValueError, match="bereits einem anderen"):
        service.remap_wix_mapping(
            case.id, expected_row_version=case.row_version, external_id="replacement-id"
        )


def test_mapping_owner_identifies_current_hub_record_and_transfer_is_audited(
    factory: sessionmaker[Session],
) -> None:
    products = ProductHubRepository(factory)
    target, _ = products.create_product(sku="XW-MAP-TARGET", name="Target")
    owner, _ = products.create_product(sku="XW-MAP-OWNER", name="Existing owner")
    old_mapping = products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=target.id, external_id="old-id"
    )
    products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=owner.id, external_id="product_taken-id"
    )
    SyncRepository(factory).create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=target.id,
        field_name="mapping",
        hub_value={"state": "mapped", "external_id": old_mapping.external_id},
        external_value={"state": "not_found", "external_id": old_mapping.external_id},
    )
    service = ConflictWizardService(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]

    found = service.wix_mapping_owner(external_id="taken-id")
    assert found is not None
    assert found["product_id"] == str(owner.id)
    assert found["product_name"] == "Existing owner"
    assert found["external_id"] == "taken-id"

    resolved = service.transfer_wix_mapping(
        case.id, expected_row_version=case.row_version, external_id="taken-id"
    )

    assert resolved.status == "RESOLVED"
    assert resolved.resolution_type == "TRANSFER_WIX_MAPPING"
    with factory() as session:
        mappings = session.query(type(old_mapping)).filter_by(channel="wix").all()
        assert len(mappings) == 1
        assert mappings[0].internal_entity_id == target.id
        assert mappings[0].external_id == "taken-id"
        assert session.execute(text("select count(*) from audit_log")).scalar_one() == 1


def test_wix_only_reconciliation_can_link_or_import_only_unique_skus(
    factory: sessionmaker[Session],
) -> None:
    products = ProductHubRepository(factory)
    existing, _ = products.create_product(sku="XW-LINK", name="Existing Hub")
    service = ConflictWizardService(factory)

    linked = service.link_wix_reconciliation_item(
        product_id=existing.id, external_id="wix-parent", variant_external_id="wix-variant"
    )
    assert linked.entity_type == "variant"
    assert linked.external_id == "wix-variant"
    assert linked.external_parent_id == "wix-parent"

    imported = service.import_wix_reconciliation_item(
        sku="XW-IMPORT", name="Imported from Wix", external_id="wix-import"
    )
    assert imported.status == "draft"
    assert products.get_product(imported.id) is not None
    mapping = products.get_channel_mapping(
        channel="wix", entity_type="product", external_id="wix-import"
    )
    assert mapping is not None and mapping.internal_entity_id == imported.id

    with pytest.raises(ValueError, match="bereits vorhanden"):
        service.import_wix_reconciliation_item(
            sku="XW-IMPORT", name="Duplicate", external_id="wix-import-two"
        )


def test_remap_to_wix_variant_keeps_the_shared_parent_available(factory: sessionmaker[Session]) -> None:
    products = ProductHubRepository(factory)
    target, target_variant = products.create_product(sku="XW-6012", name="BH Polka small")
    other, _ = products.create_product(sku="XW-6212", name="BH Polka medium")
    mapping = products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=target.id, external_id="old-id"
    )
    products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=other.id, external_id="bh-polka"
    )
    SyncRepository(factory).create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=target.id,
        field_name="mapping",
        hub_value={"state": "mapped", "external_id": mapping.external_id},
        external_value={"state": "not_found", "external_id": mapping.external_id},
    )
    service = ConflictWizardService(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]

    service.remap_wix_mapping(
        case.id,
        expected_row_version=case.row_version,
        external_id="bh-polka",
        variant_external_id="wix-small",
    )

    with factory() as session:
        remapped = session.get(type(mapping), mapping.id)
        assert remapped is not None
        assert remapped.entity_type == "variant"
        assert remapped.internal_entity_id == target_variant.id
        assert remapped.external_id == "wix-small"
        assert remapped.external_parent_id == "bh-polka"


def test_new_wix_product_is_mapped_and_audited(factory: sessionmaker[Session]) -> None:
    products = ProductHubRepository(factory)
    product, _variant = products.create_product(sku="XW-MAP-NEW", name="New Wix draft")
    mapping = products.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id="missing-id"
    )
    SyncRepository(factory).create_sync_conflict(
        channel="wix", entity_type="product", internal_entity_id=product.id, field_name="mapping",
        hub_value={"state": "mapped", "external_id": mapping.external_id},
        external_value={"state": "not_found", "external_id": mapping.external_id},
    )
    service = ConflictWizardService(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]

    resolved = service.map_new_wix_product(
        case.id, expected_row_version=case.row_version, external_id="new-wix-id"
    )

    assert resolved.resolution_type == "CREATE_WIX_PRODUCT"
    with factory() as session:
        refreshed = session.get(type(mapping), mapping.id)
        assert refreshed is not None and refreshed.external_id == "new-wix-id"
        assert session.execute(text("select count(*) from audit_log")).scalar_one() == 1


def test_archive_hub_product_closes_case_without_hard_delete(factory: sessionmaker[Session]) -> None:
    product, service = _seed(factory)
    service.scan_low_level_conflicts()
    case = service.repository.list_cases()[0][0]

    resolved = service.archive_hub_product(case.id, expected_row_version=case.row_version)

    assert resolved.resolution_type == "ARCHIVE_HUB_PRODUCT"
    with factory() as session:
        refreshed = session.get(Product, product.id)
        assert refreshed is not None
        assert refreshed.active is False
        assert refreshed.archived_at is not None
        assert refreshed.attributes["wix_publish_eligible"] is False
        assert session.query(ProductVariant).filter_by(product_id=product.id).one().active is False
        assert session.execute(text("select count(*) from audit_log")).scalar_one() == 1
    assert service.scan_low_level_conflicts()["differences_found"] == 0


def test_wix_only_reconciliation_disposition_is_durable_and_reopenable(
    factory: sessionmaker[Session],
) -> None:
    service = ConflictWizardService(factory)
    due = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30)

    deferred = service.set_wix_reconciliation_disposition(
        external_id="WIX-PARENT", variant_external_id="WIX-VARIANT",
        disposition="deferred", deferred_until=due,
    )
    assert deferred.disposition == "deferred"
    assert deferred.variant_external_id == "wix-variant"

    reopened = service.set_wix_reconciliation_disposition(
        external_id="wix-parent", variant_external_id="wix-variant", disposition="active"
    )
    assert reopened.id == deferred.id
    assert reopened.disposition == "active"
    assert reopened.deferred_until is None
    with factory() as session:
        assert session.execute(text("select count(*) from audit_log")).scalar_one() == 2


def test_conflict_api_is_independently_feature_flagged(factory: sessionmaker[Session]) -> None:
    _seed(factory)
    database_url = str(factory.kw["bind"].url)
    client = TestClient(
        create_app(
            ContentWebSettings(
                bootstrap_token="secret",
                database_url=database_url,
                product_hub_catalog_read_enabled=True,
                product_hub_edit_enabled=True,
                conflict_wizard_enabled=True,
                conflict_scan_enabled=True,
            )
        )
    )
    headers = {"Authorization": "Bearer secret"}
    scan = client.post("/api/v1/conflicts/scan", headers=headers)
    assert scan.status_code == 200
    response = client.get("/api/v1/conflicts/summary", headers=headers)
    assert response.status_code == 200
    assert response.json()["open"] == 1
    queue = client.get("/api/v1/conflicts", headers=headers).json()
    detail = client.get(f"/api/v1/conflicts/{queue['items'][0]['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["fields"][0]["observations"][1]["source"] == "wix"
