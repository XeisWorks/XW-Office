from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from scripts.product_hub.check_inventory_cutover import assess_cutover
from xw_office.models.base import Base


def test_assess_cutover_is_read_only_and_fails_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "cutover.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, class_=Session, future=True)() as session:
        before = {table.name: session.query(table).count() for table in Base.metadata.sorted_tables}

    payload = assess_cutover(database_url, shadow_enabled=False, master_enabled=False)

    assert payload["eligible"] is False
    assert payload["master_enabled"] is False
    assert any(check["code"] == "shadow_mode" and check["state"] == "blocked" for check in payload["checks"])
    with sessionmaker(bind=engine, class_=Session, future=True)() as session:
        after = {table.name: session.query(table).count() for table in Base.metadata.sorted_tables}
    assert after == before
