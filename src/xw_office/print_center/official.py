"""Read-only adapter for both existing Office product catalogues."""

from __future__ import annotations

import hashlib
import json
import time

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.shared_paths import resolve_shared_path
from xw_office.models.product_hub import Product, ProductAsset, ProductVariant, PrintRule
from xw_office.models.settings_kv import SettingKV
from xw_office.print_center.models import PrintArticle, PrintStep
from xw_office.print_center.cache import CatalogueCache, CatalogueSnapshot
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.products.catalog import ProductCatalogService, _UNRELEASED_DYNAMIC_SKUS


class LegacyProduct(BaseModel):
    sku: str
    name: str = ""
    is_digital: bool = False
    title_print_configs: dict[str, dict[str, object]] = Field(default_factory=dict)


class OfficialCatalogue:
    """Deliberately exposes only a list operation; PostgreSQL reads are read-only."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        prefer_hub: bool = False,
        cache: CatalogueCache | None = None,
    ) -> None:
        self._sessions = sessions
        self._prefer_hub = prefer_hub
        self._cache = cache
        self._snapshot = cache.read() if cache else None
        self._last_resolution = (
            time.monotonic() - max(0.0, time.time() - self._snapshot.resolved_at)
            if self._snapshot
            else 0.0
        )

    def cached_articles(self) -> list[PrintArticle]:
        return list(self._snapshot.articles) if self._snapshot else []

    def _fingerprint(self, session: Session) -> str:
        tables = (
            ("product", Product.__table__),
            ("product_variant", ProductVariant.__table__),
            ("print_rule", PrintRule.__table__),
            ("product_asset", ProductAsset.__table__),
        )
        if session.get_bind().dialect.name == "postgresql":
            # All changes, including deletions and unchanged timestamps, affect the
            # token. Only the small digest crosses the network on a cache hit.
            parts = [
                "coalesce((SELECT value_json FROM public.setting_kv "
                "WHERE key='inventory.products'), '[]')"
            ]
            for name, _table in tables:
                parts.append(
                    "coalesce((SELECT string_agg(md5(row_to_json(t)::text), '' ORDER BY t.id) "
                    f"FROM public.{name} t), '')"
                )
            digest = session.scalar(text("SELECT md5(" + " || ".join(parts) + ")"))
        else:
            rows: list[object] = [
                session.scalar(
                    select(SettingKV.value_json).where(SettingKV.key == "inventory.products")
                )
            ]
            for _name, table in tables:
                rows.append(
                    [
                        dict(row)
                        for row in session.execute(select(table).order_by(table.c.id)).mappings()
                    ]
                )
            digest = hashlib.sha256(
                json.dumps(rows, default=str, sort_keys=True).encode()
            ).hexdigest()
        return f"v1:{self._prefer_hub}:{digest}"

    def list_articles(self, *, force_refresh: bool = False) -> list[PrintArticle]:
        with self._sessions() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            fingerprint = self._fingerprint(session)
            if (
                not force_refresh
                and self._snapshot is not None
                and fingerprint == self._snapshot.fingerprint
                and time.monotonic() - self._last_resolution < 300
            ):
                return list(self._snapshot.articles)
            articles = self._load_articles(session)
            self._snapshot = CatalogueSnapshot(fingerprint=fingerprint, articles=articles)
            self._last_resolution = time.monotonic()
            if self._cache:
                self._cache.write(self._snapshot)
            return list(articles)

    def _load_articles(self, session: Session) -> list[PrintArticle]:
        raw = (
            session.scalar(
                select(SettingKV.value_json).where(SettingKV.key == "inventory.products")
            )
            or "[]"
        )
        legacy_rows = TypeAdapter(list[LegacyProduct]).validate_json(raw)
        # Reuse the Office resolver, including title-specific PDF overrides.
        catalog = ProductCatalogService(SettingKvRepository(session))
        articles: dict[str, PrintArticle] = {}
        for row in legacy_rows:
            if row.is_digital or not row.sku.strip():
                continue
            sku = row.sku.strip().upper()
            for title in ("", *row.title_print_configs):
                config = catalog.resolve_print_config(sku, title=title or row.name or sku)
                article_id = f"office:{sku}:{title}"
                articles[article_id] = PrintArticle(
                    id=article_id,
                    source="official",
                    sku=sku,
                    name=str(config.get("resolved_title") or title or row.name or sku),
                    pdf_path=str(config.get("path") or ""),
                    profile_id=str(config.get("profile_id") or ""),
                    print_plan=TypeAdapter(tuple[PrintStep, ...]).validate_python(
                        config.get("print_plan") or []
                    ),
                )
        hub_rows = session.execute(
            select(Product, ProductVariant, PrintRule)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .outerjoin(PrintRule, PrintRule.variant_id == ProductVariant.id)
            .where(
                Product.active.is_(True),
                ProductVariant.active.is_(True),
                Product.product_type != "digital",
            )
        ).all()
        assets = list(
            session.scalars(
                select(ProductAsset)
                .where(
                    ProductAsset.role == "PRINT_PDF",
                    ProductAsset.storage_kind.in_(("NETWORK_PATH", "ONEDRIVE")),
                )
                .order_by(ProductAsset.sort_order, ProductAsset.id)
            )
        )
        for product, variant, rule in hub_rows:
            sku = variant.sku.strip().upper()
            if sku in _UNRELEASED_DYNAMIC_SKUS:
                continue
            article_id = f"office:{sku}:"
            if article_id in articles and not self._prefer_hub:
                continue
            matching_assets = [
                a
                for a in assets
                if a.product_id == product.id and a.variant_id in (None, variant.id)
            ]
            asset = next(
                (a for a in matching_assets if a.variant_id == variant.id),
                matching_assets[0] if matching_assets else None,
            )
            articles[article_id] = PrintArticle(
                id=article_id,
                source="official",
                sku=sku,
                name=variant.name or product.name,
                pdf_path=resolve_shared_path(asset.uri if asset else ""),
                profile_id=rule.print_profile_id or "" if rule else "",
                print_plan=TypeAdapter(tuple[PrintStep, ...]).validate_python(
                    rule.print_plan or [] if rule else []
                ),
            )
        return sorted(articles.values(), key=lambda article: (article.name.casefold(), article.id))
