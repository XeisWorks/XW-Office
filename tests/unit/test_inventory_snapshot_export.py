from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from scripts.product_hub.export_inventory_snapshot import export_snapshot
from xw_office.models.base import Base
from xw_office.models.product_hub_inventory import InventoryLocation, InventoryStock


def test_export_inventory_snapshot_contains_inventory_state(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        location = InventoryLocation(id=uuid.uuid4(), code="MAIN", name="Hauptlager")
        session.add(location)
        session.flush()
        session.add(
            InventoryStock(
                variant_id=uuid.uuid4(), location_id=location.id, on_hand=7,
                reorder_point=5, automatic_reorder_point=6,
            )
        )
        session.commit()

    output = tmp_path / "inventory-cutover.json"
    payload = export_snapshot(database_url, output)
    assert payload["snapshot_kind"] == "product_hub_inventory_cutover"
    assert output.exists()
    stored = json.loads(output.read_text(encoding="utf-8"))
    assert stored["tables"] == payload["tables"]
    assert stored["tables"]["inventory_stock"][0]["on_hand"] == 7
