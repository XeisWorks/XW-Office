"""Persistence for own articles; no Office writes or channel mappings."""
from __future__ import annotations

from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema

from xw_office.core.database import session_scope
from xw_office.print_center.models import (
    ArticleInput, OwnArticle, PrintArticle, PrintCenterBase, PrintStep,
)


def provision_storage(engine: Engine) -> None:
    """Add only the isolated print-center schema/tables, transactionally."""
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(CreateSchema("print_center", if_not_exists=True))
        PrintCenterBase.metadata.create_all(connection)


def _article(row: OwnArticle) -> PrintArticle:
    return PrintArticle(
        id=str(row.id), source="own", name=row.name, pdf_path=row.pdf_path,
        notes=row.notes,
        print_plan=TypeAdapter(tuple[PrintStep, ...]).validate_python(row.print_plan),
        row_version=row.row_version,
    )


class OwnArticleRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def list_articles(self) -> list[PrintArticle]:
        with self._sessions() as session:
            return [_article(row) for row in session.scalars(
                select(OwnArticle).order_by(OwnArticle.name, OwnArticle.id)
            )]

    def get(self, article_id: str) -> PrintArticle:
        with self._sessions() as session:
            row = session.get(OwnArticle, UUID(article_id))
            if row is None:
                raise ValueError("Der eigene Druckartikel wurde inzwischen geloescht.")
            return _article(row)

    def save(
        self, data: ArticleInput, *, article_id: str | None = None, version: int = 1
    ) -> PrintArticle:
        with session_scope(self._sessions) as session:
            if article_id is None:
                row = OwnArticle()
                session.add(row)
            else:
                existing = session.scalar(
                    select(OwnArticle).where(OwnArticle.id == UUID(article_id)).with_for_update()
                )
                if existing is None or existing.row_version != version:
                    raise ValueError(
                        "Der Artikel wurde auf einem anderen PC geaendert oder geloescht. "
                        "Bitte neu laden."
                    )
                row = existing
                row.row_version += 1
            row.name = data.name
            row.pdf_path = data.pdf_path
            row.notes = data.notes
            row.print_plan = [step.model_dump() for step in data.print_plan]
            session.flush()
            return _article(row)

    def delete(self, article_id: str, *, version: int) -> None:
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(OwnArticle).where(OwnArticle.id == UUID(article_id)).with_for_update()
            )
            if row is None or row.row_version != version:
                raise ValueError("Der Artikel wurde inzwischen geaendert. Bitte neu laden.")
            session.delete(row)
