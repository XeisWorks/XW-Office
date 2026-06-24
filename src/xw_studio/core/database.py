"""PostgreSQL / SQLAlchemy session factory (Phase 5)."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from xw_studio.core.config import AppConfig
from xw_studio.models import ApiSecret, Base, PcRegistry, PlcShipment, SettingKV

_CORE_TABLES = (
    ApiSecret.__table__,
    PcRegistry.__table__,
    PlcShipment.__table__,
    SettingKV.__table__,
)


def _validate_database_url(database_url: str) -> str:
    """Return a normalized database URL or raise a clear ValueError."""
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("DATABASE_URL is not set")
    try:
        make_url(normalized)
    except Exception as exc:
        raise ValueError(f"DATABASE_URL is invalid: {exc}") from exc
    return normalized


def create_engine_from_config(config: AppConfig) -> Engine:
    """Create a SQLAlchemy engine from ``DATABASE_URL``."""
    database_url = _validate_database_url(config.database_url or "")
    return create_engine(database_url, pool_pre_ping=True, future=True)


def ensure_core_tables(engine: Engine) -> tuple[str, ...]:
    """Create core persistence tables when they are missing."""
    existing_tables = set(inspect(engine).get_table_names())
    missing_tables = tuple(table.name for table in _CORE_TABLES if table.name not in existing_tables)
    if missing_tables:
        tables_to_create = [table for table in _CORE_TABLES if table.name in missing_tables]
        Base.metadata.create_all(engine, tables=tables_to_create, checkfirst=True)
    return missing_tables


def create_session_factory(config: AppConfig) -> sessionmaker[Session]:
    """Return a session factory bound to a new engine."""
    engine = create_engine_from_config(config)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
