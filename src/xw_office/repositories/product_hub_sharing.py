"""Repository layer for the XW Product Hub dealer sharing schema (PR12).

Token handling lives one layer up, in ``services/product_hub/sharing.py`` —
this repository only ever sees/stores a hash, never a plaintext token.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime
import uuid
from collections.abc import Generator, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub_sharing import ExportLog, SharedCatalogView


class SharingRepository:
    """Data access for shared catalog views and their export log."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def create_share(
        self,
        *,
        title: str,
        token_hash: str,
        filter_definition: Mapping[str, object],
        field_whitelist: Sequence[str],
        sort_definition: Sequence[object] = (),
        price_list_id: uuid.UUID | None = None,
        allow_csv: bool = True,
        allow_xlsx: bool = True,
        allow_images: bool = True,
        expires_at: datetime.datetime | None = None,
        created_by: uuid.UUID | None = None,
    ) -> SharedCatalogView:
        with self._scope() as session:
            share = SharedCatalogView(
                id=uuid.uuid4(),
                title=title,
                status="active",
                token_hash=token_hash,
                filter_definition=dict(filter_definition),
                field_whitelist=list(field_whitelist),
                sort_definition=list(sort_definition),
                price_list_id=price_list_id,
                allow_csv=allow_csv,
                allow_xlsx=allow_xlsx,
                allow_images=allow_images,
                expires_at=expires_at,
                created_by=created_by,
            )
            session.add(share)
            session.flush()
            return share

    def get_share(self, share_id: uuid.UUID) -> SharedCatalogView | None:
        with self._scope() as session:
            return session.get(SharedCatalogView, share_id)

    def get_share_by_token_hash(self, token_hash: str) -> SharedCatalogView | None:
        with self._scope() as session:
            return session.scalar(
                select(SharedCatalogView).where(SharedCatalogView.token_hash == token_hash)
            )

    def list_shares(self) -> list[SharedCatalogView]:
        with self._scope() as session:
            stmt = select(SharedCatalogView).order_by(SharedCatalogView.created_at.desc())
            return list(session.scalars(stmt).all())

    def revoke_share(self, share_id: uuid.UUID) -> SharedCatalogView:
        with self._scope() as session:
            share = session.get(SharedCatalogView, share_id)
            if share is None:
                raise KeyError(f"Share {share_id} not found")
            share.status = "revoked"
            share.revoked_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return share

    def touch_last_access(self, share_id: uuid.UUID) -> None:
        with self._scope() as session:
            share = session.get(SharedCatalogView, share_id)
            if share is not None:
                share.last_access_at = datetime.datetime.now(datetime.timezone.utc)
                session.flush()

    def record_export(
        self,
        *,
        shared_view_id: uuid.UUID | None,
        export_format: str,
        row_count: int,
        query_hash: str,
        requested_by: str = "",
    ) -> ExportLog:
        with self._scope() as session:
            entry = ExportLog(
                id=uuid.uuid4(),
                shared_view_id=shared_view_id,
                format=export_format,
                row_count=row_count,
                query_hash=query_hash,
                requested_by=requested_by or None,
            )
            session.add(entry)
            session.flush()
            return entry
