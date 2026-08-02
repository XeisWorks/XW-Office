"""Encrypted API secret rows (Fernet ciphertext)."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Generator

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.api_secret import ApiSecret
from xw_office.core.database import session_scope


class ApiSecretRepository:
    """Store and load ciphertext by logical secret name."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def get_ciphertext(self, name: str) -> bytes | None:
        with self._scope() as session:
            row = session.scalar(select(ApiSecret).where(ApiSecret.name == name))
            return None if row is None else row.ciphertext

    def get_all_ciphertexts(self) -> dict[str, bytes]:
        """Load all encrypted secrets with one database round-trip."""
        with self._scope() as session:
            rows = session.scalars(select(ApiSecret)).all()
            return {str(row.name): bytes(row.ciphertext) for row in rows}

    def upsert_ciphertext(self, name: str, ciphertext: bytes) -> ApiSecret:
        with self._scope() as session:
            row = session.scalar(select(ApiSecret).where(ApiSecret.name == name))
            if row is not None:
                row.ciphertext = ciphertext
                return row
            entity = ApiSecret(name=name, ciphertext=ciphertext)
            session.add(entity)
            session.flush()
            return entity
