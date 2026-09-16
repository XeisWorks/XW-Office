"""Tests for the Wix push + reconcile + conflict service (PR11)."""
from __future__ import annotations

from decimal import Decimal
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.outbox_worker import OutboxWorker
from xw_office.services.product_hub.wix_push import WixPushService, wix_push_handler
from xw_office.services.wix.product_details_client import WixProductDetail


class _FakeWixClient:
    """Stub implementing only the two methods WixPushService calls."""

    def __init__(self, *, live: WixProductDetail | None) -> None:
        self.live = live
        self.patch_calls: list[tuple[str, str, object]] = []
        #: field_name -> (ok, error, status_code) to return; defaults to success.
        self.patch_results: dict[str, tuple[bool, str, int | None]] = {}

    def get_product(self, product_id: str) -> WixProductDetail | None:
        return self.live

    def patch_product_field_with_conflict_detection(
        self, product_id: str, *, field: str, value: object
    ) -> tuple[bool, str, int | None]:
        self.patch_calls.append((product_id, field, value))
        return self.patch_results.get(field, (True, "", None))


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.commit()
    return factory


@pytest.fixture
def repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


def _seed_mapped_product(repo: ProductHubRepository, *, external_id: str = "wix-1"):
    product, variant = repo.create_product(
        sku="XW-2000", name="Hub Name", description="Hub Description"
    )
    repo.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id=external_id
    )
    price_list = repo.get_price_list_by_code("RETAIL_EUR")
    assert price_list is not None
    repo.set_price(variant.id, price_list_id=price_list.id, gross_amount=Decimal("19.99"))
    return product, variant


def _wix_detail(
    *, name: str = "Hub Name", description: str = "Hub Description", price: float = 19.99, visible: bool = True
) -> WixProductDetail:
    return WixProductDetail(
        id="wix-1", revision="r1", name=name, description=description, price=price, visible=visible
    )


def _push_service(
    session_factory: sessionmaker[Session], wix: _FakeWixClient, *, enabled: bool = True
) -> WixPushService:
    return WixPushService(session_factory, wix_client=wix, push_enabled=lambda: enabled)  # type: ignore[arg-type]


def test_push_disabled_is_noop_no_wix_calls(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    wix = _FakeWixClient(live=_wix_detail(name="Different"))
    service = _push_service(session_factory, wix, enabled=False)

    outcome = service.push_product(product.id)

    assert outcome.status == "skipped_disabled"
    assert wix.patch_calls == []


def test_push_not_mapped_to_wix(session_factory: sessionmaker[Session], repo: ProductHubRepository) -> None:
    product, _variant = repo.create_product(sku="XW-2001", name="No Mapping")
    wix = _FakeWixClient(live=None)
    service = _push_service(session_factory, wix)

    outcome = service.push_product(product.id)

    assert outcome.status == "skipped_not_mapped"


def test_push_no_changes_when_already_in_sync(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    wix = _FakeWixClient(live=_wix_detail())  # matches hub exactly
    service = _push_service(session_factory, wix)

    outcome = service.push_product(product.id)

    assert outcome.status == "no_changes"
    assert wix.patch_calls == []


def test_push_first_time_pushes_diverging_fields(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    wix = _FakeWixClient(live=_wix_detail(name="Old Wix Name", visible=False))
    service = _push_service(session_factory, wix)

    outcome = service.push_product(product.id)

    assert outcome.status == "pushed"
    assert set(outcome.pushed_fields) == {"name", "visible"}
    pushed_field_names = {call[1] for call in wix.patch_calls}
    assert pushed_field_names == {"name", "visible"}


def test_push_is_idempotent_second_call_is_no_changes(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    wix = _FakeWixClient(live=_wix_detail(name="Old Wix Name"))
    service = _push_service(session_factory, wix)

    first = service.push_product(product.id)
    assert first.status == "pushed"

    # Simulate Wix now reflecting the pushed value (as it would after a real PATCH).
    wix.live = _wix_detail(name="Hub Name")
    second = service.push_product(product.id)

    assert second.status == "no_changes"
    assert len(wix.patch_calls) == 1  # only the first call actually pushed


def test_push_detects_drift_and_creates_conflict_without_overwriting(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    sync_repo = SyncRepository(session_factory)
    # Baseline: last known-good snapshot from a prior successful push.
    sync_repo.archive_external_payload(
        channel="wix",
        entity_type="product",
        external_id="wix-1",
        payload={"name": "Hub Name", "description": "Hub Description", "visible": "true"},
        payload_hash="irrelevant",
    )

    # Wix's live name diverged from both the baseline AND the hub's current value -
    # someone edited it directly in Wix.
    wix = _FakeWixClient(live=_wix_detail(name="Edited Directly In Wix"))
    service = _push_service(session_factory, wix)

    outcome = service.push_product(product.id)

    assert outcome.status == "conflict"
    assert [c.field for c in outcome.conflicts] == ["name"]
    assert wix.patch_calls == []  # never overwritten

    conflicts = sync_repo.list_open_sync_conflicts(channel="wix")
    assert len(conflicts) == 1
    assert conflicts[0].field_name == "name"
    assert conflicts[0].hub_value == "Hub Name"
    assert conflicts[0].external_value == "Edited Directly In Wix"


def test_push_revision_conflict_409_from_wix_creates_sync_conflict(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    wix = _FakeWixClient(live=_wix_detail(name="Old Wix Name"))
    wix.patch_results["name"] = (False, "revision mismatch", 409)
    service = _push_service(session_factory, wix)

    outcome = service.push_product(product.id)

    assert outcome.status == "conflict"
    assert [c.field for c in outcome.conflicts] == ["name"]

    sync_repo = SyncRepository(session_factory)
    conflicts = sync_repo.list_open_sync_conflicts(channel="wix")
    assert len(conflicts) == 1
    assert conflicts[0].field_name == "name"


def test_push_generic_wix_error_returns_error_status(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    wix = _FakeWixClient(live=_wix_detail(name="Old Wix Name"))
    wix.patch_results["name"] = (False, "network blip", None)
    service = _push_service(session_factory, wix)

    outcome = service.push_product(product.id)

    assert outcome.status == "error"
    assert "network blip" in (outcome.error or "")


def test_resolve_conflict_keep_hub_and_push_forces_write(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    sync_repo = SyncRepository(session_factory)
    conflict = sync_repo.create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        field_name="name",
        hub_value="Hub Name",
        external_value="Wix Edited",
    )
    wix = _FakeWixClient(live=_wix_detail(name="Wix Edited"))
    service = _push_service(session_factory, wix)

    service.resolve_conflict(conflict.id, resolution="keep_hub_and_push")

    assert wix.patch_calls == [("wix-1", "name", "Hub Name")]
    resolved = sync_repo.get_sync_conflict(conflict.id)
    assert resolved is not None
    assert resolved.resolution == "keep_hub_and_push"
    assert resolved.resolved_at is not None


def test_resolve_conflict_keep_hub_and_push_blocked_when_disabled(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    sync_repo = SyncRepository(session_factory)
    conflict = sync_repo.create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        field_name="name",
        hub_value="Hub Name",
        external_value="Wix Edited",
    )
    wix = _FakeWixClient(live=_wix_detail(name="Wix Edited"))
    service = _push_service(session_factory, wix, enabled=False)

    with pytest.raises(RuntimeError):
        service.resolve_conflict(conflict.id, resolution="keep_hub_and_push")


def test_resolve_conflict_accept_external_updates_hub_product(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    sync_repo = SyncRepository(session_factory)
    conflict = sync_repo.create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        field_name="name",
        hub_value="Hub Name",
        external_value="Wix Edited",
    )
    wix = _FakeWixClient(live=_wix_detail(name="Wix Edited"))
    service = _push_service(session_factory, wix)

    service.resolve_conflict(conflict.id, resolution="accept_external")

    updated = repo.get_product(product.id)
    assert updated is not None
    assert updated.name == "Wix Edited"
    assert wix.patch_calls == []  # accept_external never writes to Wix


def test_resolve_conflict_accept_external_price_creates_new_price_row(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, variant = _seed_mapped_product(repo)
    sync_repo = SyncRepository(session_factory)
    conflict = sync_repo.create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        field_name="price",
        hub_value="19.99",
        external_value="24.99",
    )
    wix = _FakeWixClient(live=_wix_detail(price=24.99))
    service = _push_service(session_factory, wix)

    service.resolve_conflict(conflict.id, resolution="accept_external")

    prices = repo.list_prices(variant.id)
    current = next(p for p in prices if p.valid_until is None)
    assert current.gross_amount == Decimal("24.99")


def test_resolve_conflict_ignore_once_touches_nothing(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    sync_repo = SyncRepository(session_factory)
    conflict = sync_repo.create_sync_conflict(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        field_name="name",
        hub_value="Hub Name",
        external_value="Wix Edited",
    )
    wix = _FakeWixClient(live=_wix_detail(name="Wix Edited"))
    service = _push_service(session_factory, wix)

    service.resolve_conflict(conflict.id, resolution="ignore_once")

    assert wix.patch_calls == []
    updated = repo.get_product(product.id)
    assert updated is not None
    assert updated.name == "Hub Name"  # untouched
    resolved = sync_repo.get_sync_conflict(conflict.id)
    assert resolved is not None
    assert resolved.resolution == "ignore_once"


# -- outbox integration ----------------------------------------------------------


def test_wix_push_handler_resolves_product_updated_event(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    wix = _FakeWixClient(live=_wix_detail(name="Old Wix Name"))
    service = _push_service(session_factory, wix)
    handler = wix_push_handler(service, repo)

    from xw_office.repositories.product_hub_sync import append_outbox_event

    with session_factory() as session:
        event = append_outbox_event(
            session,
            aggregate_type="product",
            aggregate_id=product.id,
            event_type="product.updated",
            payload={},
        )
        session.commit()
        event_obj = event

    handler(event_obj)

    assert wix.patch_calls  # pushed


def test_wix_push_handler_resolves_price_changed_event_via_variant(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, variant = _seed_mapped_product(repo)
    wix = _FakeWixClient(live=_wix_detail(price=9.99))
    service = _push_service(session_factory, wix)
    handler = wix_push_handler(service, repo)

    from xw_office.repositories.product_hub_sync import append_outbox_event

    with session_factory() as session:
        event = append_outbox_event(
            session,
            aggregate_type="product_variant",
            aggregate_id=variant.id,
            event_type="price.changed",
            payload={},
        )
        session.commit()
        event_obj = event

    handler(event_obj)

    assert ("wix-1", "price", 19.99) in wix.patch_calls


def test_outbox_worker_retries_wix_push_failure(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, _variant = _seed_mapped_product(repo)
    wix = _FakeWixClient(live=_wix_detail(name="Old Wix Name"))
    wix.patch_results["name"] = (False, "network blip", None)
    service = _push_service(session_factory, wix)
    handler = wix_push_handler(service, repo)

    worker = OutboxWorker(session_factory)
    worker.register_handler("product.updated", handler)

    from xw_office.repositories.product_hub_sync import append_outbox_event

    with session_factory() as session:
        append_outbox_event(
            session,
            aggregate_type="product",
            aggregate_id=product.id,
            event_type="product.updated",
            payload={},
        )
        session.commit()

    summary = worker.process_once()

    assert summary.failed == 1
    assert any("network blip" in err for err in summary.errors)
