"""Ideas JSON store tests."""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.repositories import SettingKvRepository
from xw_office.services.ideas.store import IdeaEntry, IdeasStore


@pytest.fixture
def ideas_path(tmp_path: Path) -> Path:
    return tmp_path / "ideas.json"


def test_add_and_list(ideas_path: Path) -> None:
    store = IdeasStore(ideas_path)
    store.add_idea(IdeaEntry(title="A", body="alpha"))
    store.add_idea(IdeaEntry(title="B", body="beta"))
    rows = store.list_ideas()
    assert len(rows) == 2
    assert rows[0].title == "A"


def test_database_store_migrates_local_file_and_remains_shared(ideas_path: Path) -> None:
    ideas_path.write_text(
        json.dumps([{"title": "Lokal", "body": "wird migriert"}]),
        encoding="utf-8",
    )
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
    repo = SettingKvRepository(factory)

    first_pc = IdeasStore(ideas_path, repo, "ideas.shared")
    second_pc = IdeasStore(ideas_path, repo, "ideas.shared")
    second_pc.add_idea(IdeaEntry(title="Railway", body="gemeinsam"))

    assert [row.title for row in first_pc.list_ideas()] == ["Lokal", "Railway"]
    assert repo.get_value_json("ideas.shared") is not None


def test_database_store_does_not_overwrite_existing_shared_data(ideas_path: Path) -> None:
    ideas_path.write_text(
        json.dumps([{"title": "Veraltet", "body": "lokale Kopie"}]),
        encoding="utf-8",
    )
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
    repo = SettingKvRepository(factory)
    repo.set_value_json(
        "ideas.shared",
        json.dumps([{"title": "Aktuell", "body": "Railway"}]),
    )

    store = IdeasStore(ideas_path, repo, "ideas.shared")

    assert [row.title for row in store.list_ideas()] == ["Aktuell"]
