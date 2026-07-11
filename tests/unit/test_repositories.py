"""Repository integration tests (SQLite in-memory)."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_studio.models.base import Base
from xw_studio.repositories import ApiSecretRepository, PcRegistryRepository, PlcShipmentRepository, SettingKvRepository


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


def test_setting_kv_mutate_value_json(session_factory: sessionmaker[Session]) -> None:
    repo = SettingKvRepository(session_factory)
    repo.set_value_json("shared.items", '["first"]')

    updated = repo.mutate_value_json(
        "shared.items",
        lambda raw: json.dumps([*json.loads(raw or "[]"), "second"]),
    )

    assert json.loads(updated) == ["first", "second"]
    assert json.loads(repo.get_value_json("shared.items") or "[]") == ["first", "second"]


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
