"""Transactional storage for the resumable Product Hub wizard."""
from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import (
    ProductDraft,
    ProductDraftOption,
    ProductDraftVariant,
    ProductSkuAlias,
    ProductVariant,
)
from xw_office.repositories.product_hub import OptimisticLockError, normalize_sku


class ProductDraftRepository:
    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    @staticmethod
    def _touch(draft: ProductDraft) -> None:
        draft.row_version += 1
        draft.updated_at = datetime.datetime.now(datetime.timezone.utc)

    @staticmethod
    def _require_version(draft: ProductDraft, expected: int) -> None:
        if draft.row_version != expected:
            raise OptimisticLockError(
                f"Draft {draft.id} row_version is {draft.row_version}, expected {expected}"
            )

    def create(
        self, *, source_product_id: uuid.UUID | None = None, template_code: str = "",
        data: dict[str, object] | None = None,
    ) -> ProductDraft:
        with self._scope() as session:
            draft = ProductDraft(
                id=uuid.uuid4(), source_product_id=source_product_id,
                template_code=template_code.strip() or None, data=data or {},
                completed_steps=[], current_step=0, schema_version=1, row_version=1,
            )
            session.add(draft)
            session.flush()
            return draft

    def get(self, draft_id: uuid.UUID) -> ProductDraft | None:
        with self._scope() as session:
            return session.get(ProductDraft, draft_id)

    def list(self, *, limit: int = 50) -> list[ProductDraft]:
        with self._scope() as session:
            return list(session.scalars(
                select(ProductDraft).order_by(ProductDraft.updated_at.desc()).limit(limit)
            ).all())

    def update(self, draft_id: uuid.UUID, *, expected_row_version: int, **fields: object) -> ProductDraft:
        allowed = {"current_step", "completed_steps", "data", "template_code"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown draft field(s): {', '.join(sorted(unknown))}")
        with self._scope() as session:
            draft = session.get(ProductDraft, draft_id)
            if draft is None:
                raise KeyError(f"Draft {draft_id} not found")
            self._require_version(draft, expected_row_version)
            for name, value in fields.items():
                setattr(draft, name, value)
            self._touch(draft)
            session.flush()
            return draft

    def list_options(self, draft_id: uuid.UUID) -> list[ProductDraftOption]:
        with self._scope() as session:
            return list(session.scalars(
                select(ProductDraftOption).where(ProductDraftOption.draft_id == draft_id)
                .order_by(ProductDraftOption.sort_order, ProductDraftOption.name)
            ).all())

    def add_option(self, draft_id: uuid.UUID, *, expected_draft_row_version: int, name: str,
                   values: list[object], sort_order: int = 0) -> ProductDraftOption:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Option name is required")
        clean_values = [str(value).strip() for value in values if str(value).strip()]
        if not clean_values:
            raise ValueError("Option values are required")
        if len({value.casefold() for value in clean_values}) != len(clean_values):
            raise ValueError("Option values must be unique")
        with self._scope() as session:
            draft = session.get(ProductDraft, draft_id)
            if draft is None:
                raise KeyError(f"Draft {draft_id} not found")
            self._require_version(draft, expected_draft_row_version)
            option = ProductDraftOption(
                id=uuid.uuid4(), draft_id=draft_id, name=clean_name, values=clean_values,
                sort_order=sort_order, row_version=1,
            )
            session.add(option)
            self._touch(draft)
            session.flush()
            return option

    def list_variants(self, draft_id: uuid.UUID) -> list[ProductDraftVariant]:
        with self._scope() as session:
            return list(session.scalars(
                select(ProductDraftVariant).where(ProductDraftVariant.draft_id == draft_id)
                .order_by(ProductDraftVariant.sku)
            ).all())

    def add_variant(self, draft_id: uuid.UUID, *, expected_draft_row_version: int, sku: str,
                    option_values: dict[str, object], price_gross: Decimal | None,
                    tax_rate: Decimal | None, currency: str = "EUR", selected: bool = True,
                    ) -> ProductDraftVariant:
        clean_sku = normalize_sku(sku)
        if not clean_sku:
            raise ValueError("SKU is required")
        with self._scope() as session:
            draft = session.get(ProductDraft, draft_id)
            if draft is None:
                raise KeyError(f"Draft {draft_id} not found")
            self._require_version(draft, expected_draft_row_version)
            variant = ProductDraftVariant(
                id=uuid.uuid4(), draft_id=draft_id, sku=clean_sku,
                option_values={str(k).strip(): str(v).strip() for k, v in option_values.items() if str(k).strip()},
                price_gross=price_gross, tax_rate=tax_rate, currency=currency.upper(), selected=selected,
                row_version=1,
            )
            session.add(variant)
            self._touch(draft)
            session.flush()
            return variant

    def sku_available(self, sku: str) -> bool:
        clean_sku = normalize_sku(sku)
        if not clean_sku:
            return False
        with self._scope() as session:
            variant_exists = session.scalar(
                select(ProductVariant.id).where(func.upper(ProductVariant.sku) == clean_sku).limit(1)
            )
            alias_exists = session.scalar(
                select(ProductSkuAlias.id).where(func.upper(ProductSkuAlias.alias_sku) == clean_sku).limit(1)
            )
            return variant_exists is None and alias_exists is None
