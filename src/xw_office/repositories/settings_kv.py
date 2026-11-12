"""Key-value settings in PostgreSQL."""
from __future__ import annotations

import datetime
from contextlib import contextmanager
from collections.abc import Callable, Generator

from sqlalchemy import select, text
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

    def get_value_json_with_updated_at(
        self, key: str
    ) -> tuple[str | None, datetime.datetime | None]:
        """Read a setting payload and its shared revision in one database round trip."""
        with self._scope() as session:
            row = session.get(SettingKV, key)
            return (None, None) if row is None else (row.value_json, row.updated_at)

    def get_values_json(self, keys: list[str] | tuple[str, ...]) -> dict[str, str]:
        """Read several settings in one query and one database round trip."""
        clean_keys = tuple(dict.fromkeys(key for key in keys if key))
        if not clean_keys:
            return {}
        with self._scope() as session:
            rows = session.execute(
                select(SettingKV.key, SettingKV.value_json).where(SettingKV.key.in_(clean_keys))
            ).all()
            return {key: value_json for key, value_json in rows}

    def list_values_json_by_prefix(self, prefix: str) -> dict[str, str]:
        """List settings with one namespace prefix in deterministic key order."""
        clean_prefix = str(prefix or "")
        if not clean_prefix.strip():
            raise ValueError("SettingKV-Praefix darf nicht leer sein")
        with self._scope() as session:
            rows = session.scalars(
                select(SettingKV)
                .where(SettingKV.key.startswith(clean_prefix, autoescape=True))
                .order_by(SettingKV.key)
            ).all()
            return {row.key: row.value_json for row in rows}

    @contextmanager
    def advisory_lock(self, key: str) -> Generator[None, None, None]:
        """Hold a transaction-scoped PostgreSQL lock while a caller performs I/O.

        This is intended for short, serialized read/modify/write operations whose
        external system does not provide an atomic increment endpoint. The caller
        must keep the protected operation bounded and must not invoke UI work here.
        """
        lock_key = str(key or "").strip()
        if not lock_key:
            raise ValueError("Advisory-Lock-Schluessel darf nicht leer sein")
        with self._scope() as session:
            bind = session.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": lock_key},
                )
            yield

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

    def mutate_values_json(
        self,
        mutations: dict[str, Callable[[str | None], str]],
    ) -> dict[str, str]:
        """Apply several JSON setting mutations in one transaction.

        PostgreSQL advisory locks are acquired in sorted-key order to serialize
        cross-process writers without deadlocks. This is used when a legacy stock
        snapshot and its idempotency journal must commit as one operation.
        """
        if not mutations:
            return {}
        keys = list(mutations)
        updated: dict[str, str] = {}
        with self._scope() as session:
            bind = session.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                for key in sorted(keys):
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                        {"key": key},
                    )
            rows = {
                row.key: row
                for row in session.scalars(
                    select(SettingKV).where(SettingKV.key.in_(keys)).with_for_update()
                ).all()
            }
            for key, mutator in mutations.items():
                row = rows.get(key)
                current = None if row is None else row.value_json
                value = mutator(current)
                updated[key] = value
                if row is None:
                    session.add(SettingKV(key=key, value_json=value))
                else:
                    row.value_json = value
            session.flush()
        return updated
