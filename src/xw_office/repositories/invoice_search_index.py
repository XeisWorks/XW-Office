"""Persistence for the shared sevDesk invoice search index."""
from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.invoice_search_index import InvoiceSearchIndex

_UPSERT_CHUNK = 400
_UPSERT_COLUMNS = (
    "invoice_number",
    "invoice_date",
    "status_code",
    "search_text",
    "payload_json",
    "synced_at",
)


@dataclass(frozen=True)
class InvoiceIndexRow:
    invoice_id: str
    invoice_number: str
    invoice_date: str | None
    status_code: int | None
    search_text: str
    payload_json: str
    synced_at: float


class InvoiceSearchIndexRepository:
    """Read/write access to ``invoice_search_index``."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def upsert_many(self, rows: Sequence[InvoiceIndexRow]) -> int:
        unique = {row.invoice_id: row for row in rows if row.invoice_id}
        if not unique:
            return 0
        values = [
            {
                "invoice_id": row.invoice_id,
                "invoice_number": row.invoice_number[:100],
                "invoice_date": row.invoice_date,
                "status_code": row.status_code,
                "search_text": row.search_text,
                "payload_json": row.payload_json,
                "synced_at": row.synced_at,
            }
            for row in unique.values()
        ]
        with self._scope() as session:
            insert = self._insert_for(session)
            for start in range(0, len(values), _UPSERT_CHUNK):
                chunk = values[start : start + _UPSERT_CHUNK]
                stmt = insert(InvoiceSearchIndex).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[InvoiceSearchIndex.invoice_id],
                    set_={column: stmt.excluded[column] for column in _UPSERT_COLUMNS},
                )
                session.execute(stmt)
        return len(values)

    @staticmethod
    def _insert_for(session: Session):  # type: ignore[no-untyped-def]
        bind = session.get_bind()
        dialect = bind.dialect.name if bind is not None else ""
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            return pg_insert
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            return sqlite_insert
        raise RuntimeError(f"Invoice search index does not support dialect {dialect!r}")

    def search(self, tokens: Sequence[str], *, limit: int = 500) -> list[InvoiceIndexRow]:
        """Return rows whose normalized text contains every token (newest first)."""
        stmt = select(InvoiceSearchIndex)
        for token in tokens:
            escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(InvoiceSearchIndex.search_text.like(f"%{escaped}%", escape="\\"))
        stmt = stmt.order_by(
            func.length(InvoiceSearchIndex.invoice_id).desc(),
            InvoiceSearchIndex.invoice_id.desc(),
        ).limit(max(1, int(limit)))
        with self._scope() as session:
            return [self._to_row(entity) for entity in session.scalars(stmt)]

    def delete(self, invoice_id: str) -> None:
        with self._scope() as session:
            session.execute(
                delete(InvoiceSearchIndex).where(InvoiceSearchIndex.invoice_id == str(invoice_id))
            )

    def count(self) -> int:
        with self._scope() as session:
            return int(session.scalar(select(func.count()).select_from(InvoiceSearchIndex)) or 0)

    def oldest_invoice_date(self) -> str | None:
        with self._scope() as session:
            value = session.scalar(
                select(func.min(InvoiceSearchIndex.invoice_date)).where(
                    InvoiceSearchIndex.invoice_date.is_not(None),
                    InvoiceSearchIndex.invoice_date != "",
                )
            )
        return None if value is None else str(value)

    @staticmethod
    def _to_row(entity: InvoiceSearchIndex) -> InvoiceIndexRow:
        return InvoiceIndexRow(
            invoice_id=entity.invoice_id,
            invoice_number=entity.invoice_number,
            invoice_date=entity.invoice_date,
            status_code=entity.status_code,
            search_text=entity.search_text,
            payload_json=entity.payload_json,
            synced_at=float(entity.synced_at),
        )
