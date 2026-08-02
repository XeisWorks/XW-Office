"""PC registry persistence."""
from __future__ import annotations

import datetime
from contextlib import contextmanager
from collections.abc import Generator

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.pc_registry import PcRegistry
from xw_office.core.database import session_scope


class PcRegistryRepository:
    """CRUD-style access for workstation rows."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        # If we were given an actual Session, we must NOT close/commit it here.
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def get_by_machine_id(self, machine_id: str) -> PcRegistry | None:
        with self._scope() as session:
            return session.scalar(
                select(PcRegistry).where(PcRegistry.machine_id == machine_id),
            )

    def upsert_last_seen(
        self,
        machine_id: str,
        *,
        display_name: str | None = None,
        is_print_station: bool = False,
    ) -> PcRegistry:
        """Create or update ``last_seen_at`` and optional fields."""
        now = datetime.datetime.now(datetime.UTC)
        with self._scope() as session:
            row = session.scalar(
                select(PcRegistry).where(PcRegistry.machine_id == machine_id),
            )
            if row is not None:
                row.last_seen_at = now
                if display_name is not None:
                    row.display_name = display_name
                row.is_print_station = is_print_station
                return row
            entity = PcRegistry(
                machine_id=machine_id,
                display_name=display_name,
                is_print_station=is_print_station,
                last_seen_at=now,
            )
            session.add(entity)
            session.flush()
            return entity
