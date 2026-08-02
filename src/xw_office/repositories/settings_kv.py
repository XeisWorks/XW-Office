"""Key-value settings in PostgreSQL."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable, Generator

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.settings_kv import SettingKV
from xw_office.core.database import session_scope


class SettingKvRepository:
    """Read/write JSON text blobs by string key."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def get_value_json(self, key: str) -> str | None:
        with self._scope() as session:
            row = session.get(SettingKV, key)
            return None if row is None else row.value_json

    def set_value_json(self, key: str, value_json: str) -> SettingKV:
        with self._scope() as session:
            row = session.get(SettingKV, key)
            if row is not None:
                row.value_json = value_json
                return row
            entity = SettingKV(key=key, value_json=value_json)
            session.add(entity)
            session.flush()
            return entity

    def mutate_value_json(
        self,
        key: str,
        mutator: Callable[[str | None], str],
    ) -> str:
        """Atomically update one JSON blob, serializing writers per key in PostgreSQL."""
        with self._scope() as session:
            bind = session.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": key},
                )
            row = session.get(SettingKV, key)
            current = None if row is None else row.value_json
            updated = mutator(current)
            if row is None:
                row = SettingKV(key=key, value_json=updated)
                session.add(row)
            else:
                row.value_json = updated
            session.flush()
            return updated
