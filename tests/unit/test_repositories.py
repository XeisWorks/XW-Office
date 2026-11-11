"""Repository integration tests (SQLite in-memory)."""
from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories import (
    ApiSecretRepository,
    CustomerAftercareRepository,
    PcRegistryRepository,
    PlcShipmentRepository,
    SettingKvRepository,
)
from xw_office.repositories.customer_aftercare import CustomerAftercareItemInput


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def test_pc_registry_upsert_and_fetch(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        repo = PcRegistryRepository(s)
        row = repo.upsert_last_seen("win-pc-1", display_name="Büro-1", is_print_station=True)
        s.commit()
        pc_id = row.id

    with session_factory() as s:
        repo = PcRegistryRepository(s)
        again = repo.get_by_machine_id("win-pc-1")
        assert again is not None
        assert again.id == pc_id
        assert again.display_name == "Büro-1"
        assert again.is_print_station is True


def test_setting_kv_round_trip(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        repo = SettingKvRepository(s)
        repo.set_value_json("ui.theme", '{"mode":"dark"}')
        s.commit()

    with session_factory() as s:
        repo = SettingKvRepository(s)
        raw = repo.get_value_json("ui.theme")
        assert raw == '{"mode":"dark"}'


def test_setting_kv_reads_multiple_values_in_one_call(session_factory: sessionmaker[Session]) -> None:
    repo = SettingKvRepository(session_factory)
    repo.set_value_json("ui.theme", '{"mode":"dark"}')
    repo.set_value_json("ui.language", '"de"')

    assert repo.get_values_json(["ui.theme", "ui.language", "missing"]) == {
        "ui.theme": '{"mode":"dark"}',
        "ui.language": '"de"',
    }
    assert repo.get_values_json([]) == {}


def test_setting_kv_lists_values_by_prefix_in_key_order(
    session_factory: sessionmaker[Session],
) -> None:
    repo = SettingKvRepository(session_factory)
    repo.set_value_json("claims:b", '{"state":"unknown"}')
    repo.set_value_json("other:a", '{"state":"unknown"}')
    repo.set_value_json("claims:a", '{"state":"failed"}')

    assert repo.list_values_json_by_prefix("claims:") == {
        "claims:a": '{"state":"failed"}',
        "claims:b": '{"state":"unknown"}',
    }
    with pytest.raises(ValueError, match="darf nicht leer"):
        repo.list_values_json_by_prefix(" ")


def test_setting_kv_mutate_value_json(session_factory: sessionmaker[Session]) -> None:
    repo = SettingKvRepository(session_factory)
    repo.set_value_json("shared.items", '["first"]')

    updated = repo.mutate_value_json(
        "shared.items",
        lambda raw: json.dumps([*json.loads(raw or "[]"), "second"]),
    )

    assert json.loads(updated) == ["first", "second"]
    assert json.loads(repo.get_value_json("shared.items") or "[]") == ["first", "second"]


def test_setting_kv_advisory_lock_context_is_usable_without_postgres(
    session_factory: sessionmaker[Session],
) -> None:
    repo = SettingKvRepository(session_factory)

    with repo.advisory_lock("sevdesk-part-stock:part-1"):
        repo.set_value_json("lock.test", '{"inside":true}')

    assert repo.get_value_json("lock.test") == '{"inside":true}'

    with pytest.raises(ValueError, match="darf nicht leer"):
        with repo.advisory_lock(" "):
            pass


def test_api_secret_upsert(session_factory: sessionmaker[Session]) -> None:
    blob = b"\x00cipher-demo\x00"
    with session_factory() as s:
        repo = ApiSecretRepository(s)
        repo.upsert_ciphertext("SEVDESK", blob)
        s.commit()

    with session_factory() as s:
        repo = ApiSecretRepository(s)
        assert repo.get_ciphertext("SEVDESK") == blob
        assert repo.get_all_ciphertexts() == {"SEVDESK": blob}

    with session_factory() as s:
        repo = ApiSecretRepository(s)
        repo.upsert_ciphertext("SEVDESK", b"\x02updated\x02")
        s.commit()

    with session_factory() as s:
        repo = ApiSecretRepository(s)
        assert repo.get_ciphertext("SEVDESK") == b"\x02updated\x02"


def test_plc_shipment_reservation_blocks_duplicate_after_creation(
    session_factory: sessionmaker[Session],
) -> None:
    repo = PlcShipmentRepository(session_factory)
    first = repo.reserve(
        request_key="a" * 64,
        invoice_id="invoice-1",
        reference="20856",
        invoice_number="RE-1",
        mode="TEST",
        transport="webservice",
        product_code="10",
        country_iso2="AT",
    )
    assert first.state == "reserved"
    repo.mark_created("a" * 64, tracking_codes=("TRACK-1",), label_sha256="b" * 64)

    duplicate = repo.reserve(
        request_key="a" * 64,
        invoice_id="invoice-1",
        reference="20856",
        invoice_number="RE-1",
        mode="TEST",
        transport="webservice",
        product_code="10",
        country_iso2="AT",
    )
    assert duplicate.state == "already_created"
    assert duplicate.shipment.status == "created"


def test_plc_parcel_evidence_requires_explicit_code_assignment_for_multiple_packages(
    session_factory: sessionmaker[Session],
) -> None:
    repo = PlcShipmentRepository(session_factory)
    key = "c" * 64
    repo.reserve(
        request_key=key, invoice_id="invoice-2", reference="20857",
        invoice_number="RE-2", mode="TEST", transport="webservice",
        product_code="10", country_iso2="AT",
        parcel_snapshots=(
            {"reference": "20857-P1", "weight_kg": "0.5", "contents": [
                {"quantity": 2, "name": "Alpenmarsch", "sku": "XW-400"}
            ]},
            {"reference": "20857-P2", "weight_kg": "0.6", "contents": [
                {"quantity": 1, "name": "Bergklang", "sku": "XW-401"}
            ]},
        ),
    )
    repo.mark_created(
        key, tracking_codes=("CODE-1", "CODE-2"),
        collo_codes=(("CODE-2",), ("CODE-1",)), label_sha256="d" * 64,
    )
    evidence = repo.list_parcel_evidence(invoice_id="invoice-2")
    assert [entry.tracking_code for entry in evidence] == ["", ""]
    assert [entry.contents[0]["name"] for entry in evidence] == ["Alpenmarsch", "Bergklang"]
    assert repo.confirm_parcel_code(
        shipment_id=evidence[0].shipment_id, package_number=1, tracking_code="CODE-1"
    )
    assert not repo.confirm_parcel_code(
        shipment_id=evidence[0].shipment_id, package_number=2, tracking_code="CODE-1"
    )
    assert not repo.confirm_parcel_code(
        shipment_id=evidence[0].shipment_id, package_number=2, tracking_code="FOREIGN"
    )
    assert repo.list_parcel_evidence(invoice_id="invoice-2")[0].code_assignment == "operator_confirmed"


def test_plc_single_parcel_code_is_assigned_without_operator_guess(
    session_factory: sessionmaker[Session],
) -> None:
    repo = PlcShipmentRepository(session_factory)
    key = "e" * 64
    repo.reserve(
        request_key=key, invoice_id="invoice-3", reference="20858",
        invoice_number="RE-3", mode="TEST", transport="webservice",
        product_code="10", country_iso2="AT",
        parcel_snapshots=({"reference": "20858", "weight_kg": "0.7", "contents": []},),
    )
    repo.mark_created(key, tracking_codes=("ONLY-CODE",), label_sha256="f" * 64)
    entry = repo.list_parcel_evidence(invoice_id="invoice-3")[0]
    assert entry.tracking_code == "ONLY-CODE"
    assert entry.code_assignment == "single_parcel"
    assert entry.confirmed_at is None


def test_plc_imports_only_known_post_tracking_events_once(
    session_factory: sessionmaker[Session],
) -> None:
    repo = PlcShipmentRepository(session_factory)
    key = "1" * 64
    repo.reserve(
        request_key=key, invoice_id="invoice-4", reference="20859",
        invoice_number="RE-4", mode="LIVE", transport="webservice",
        product_code="10", country_iso2="AT",
        parcel_snapshots=({"reference": "20859", "weight_kg": "0.4", "contents": []},),
    )
    repo.mark_created(key, tracking_codes=("KNOWN",), label_sha256="2" * 64)
    raw = b"""<t:TrackingData xmlns:t="http://Post.at/Pis/TrackingProcessor/Default/TrackingEvent_V2.0.0">
      <TrackingEvents><Header><TrackingVersion>2</TrackingVersion><EventCount>2</EventCount></Header>
        <Event><ParcelEventId>123</ParcelEventId><IdentCode>KNOWN</IdentCode>
          <EventTimestamp>2026-11-10T10:11:12.000</EventTimestamp>
          <ParcelEventTypeCode>ZUS</ParcelEventTypeCode><ParcelEventReasonCode>ZP</ParcelEventReasonCode>
        </Event>
        <Event><ParcelEventId>124</ParcelEventId><IdentCode>OTHER</IdentCode>
          <EventTimestamp>2026-11-10T10:12:12.000</EventTimestamp>
          <ParcelEventTypeCode>AVI</ParcelEventTypeCode>
        </Event>
      </TrackingEvents></t:TrackingData>"""
    assert repo.import_post_tracking_xml(raw, invoice_id="invoice-4") == 1
    assert repo.import_post_tracking_xml(raw, invoice_id="invoice-4") == 0
    entry = repo.list_parcel_evidence(invoice_id="invoice-4")[0]
    assert [(event.event_type, event.event_reason) for event in entry.events] == [("ZUS", "ZP")]
    assert len(entry.events[0].source_sha256) == 64


def test_customer_aftercare_reserve_by_message_id_is_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    repo = CustomerAftercareRepository(session_factory)

    first = repo.reserve_case_by_message_id(
        source_message_id="graph-msg-1",
        ai_suggested_type="B2B_WRONG_DELIVERY",
        customer_email="haendler@example.com",
    )
    assert first.state == "created"
    assert first.case.status == "PENDING_REVIEW"

    duplicate = repo.reserve_case_by_message_id(
        source_message_id="graph-msg-1",
        ai_suggested_type="B2B_WRONG_DELIVERY",
        customer_email="haendler@example.com",
    )
    assert duplicate.state == "already_exists"
    assert duplicate.case.id == first.case.id
    assert repo.count_pending_review() == 1


def test_customer_aftercare_items_round_trip(session_factory: sessionmaker[Session]) -> None:
    repo = CustomerAftercareRepository(session_factory)
    reservation = repo.reserve_case_by_message_id(source_message_id="graph-msg-2")

    repo.add_items(
        reservation.case.id,
        [
            CustomerAftercareItemInput(role="WRONG_DELIVERED", sku="XW-100", quantity=1),
            CustomerAftercareItemInput(role="MISSING_TO_SEND", sku="XW-200", quantity=2),
        ],
    )

    items = repo.get_items(reservation.case.id)
    assert {item.role for item in items} == {"WRONG_DELIVERED", "MISSING_TO_SEND"}


def test_customer_aftercare_waiting_to_triggered_is_atomic_and_blocks_retrigger(
    session_factory: sessionmaker[Session],
) -> None:
    repo = CustomerAftercareRepository(session_factory)
    reservation = repo.reserve_case_by_message_id(source_message_id="graph-msg-3")
    due_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=20)
    repo.confirm_classification(
        reservation.case.id,
        case_type="B2B_WRONG_DELIVERY",
        courtesy=True,
        customer_type="B2B",
        wait_for_next_order=True,
        due_at=due_at,
        trigger_now=False,
    )

    triggered = repo.try_transition_waiting_to_triggered(
        reservation.case.id,
        reason="NEW_ORDER",
        trigger_wix_order_id="order-2",
        trigger_wix_order_number="20900",
    )
    assert triggered is not None
    assert triggered.status == "TRIGGERED"
    assert triggered.trigger_reason == "NEW_ORDER"

    second_attempt = repo.try_transition_waiting_to_triggered(
        reservation.case.id, reason="MAX_WAIT_EXPIRED"
    )
    assert second_attempt is None
    assert repo.get_case(reservation.case.id).trigger_reason == "NEW_ORDER"


def test_customer_aftercare_count_due_includes_triggered_and_overdue_waiting(
    session_factory: sessionmaker[Session],
) -> None:
    repo = CustomerAftercareRepository(session_factory)
    now = datetime.datetime.now(datetime.timezone.utc)

    overdue = repo.reserve_case_by_message_id(source_message_id="graph-msg-4")
    repo.confirm_classification(
        overdue.case.id,
        case_type="B2B_MISSING_ITEMS",
        courtesy=True,
        customer_type="B2B",
        wait_for_next_order=True,
        due_at=now - datetime.timedelta(days=1),
        trigger_now=False,
    )

    not_yet_due = repo.reserve_case_by_message_id(source_message_id="graph-msg-5")
    repo.confirm_classification(
        not_yet_due.case.id,
        case_type="B2B_MISSING_ITEMS",
        courtesy=True,
        customer_type="B2B",
        wait_for_next_order=True,
        due_at=now + datetime.timedelta(days=10),
        trigger_now=False,
    )

    immediate = repo.reserve_case_by_message_id(source_message_id="graph-msg-6")
    repo.confirm_classification(
        immediate.case.id,
        case_type="B2C_WRONG_DELIVERY",
        courtesy=True,
        customer_type="B2C",
        wait_for_next_order=False,
        due_at=None,
        trigger_now=True,
    )

    assert repo.count_due(now=now) == 2
    due_cases = repo.list_due_waiting_cases(now=now)
    assert [case.id for case in due_cases] == [overdue.case.id]
