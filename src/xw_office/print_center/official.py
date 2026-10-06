"""Read-only adapter for both existing Office product catalogues."""
from __future__ import annotations

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.shared_paths import resolve_shared_path
from xw_office.models.product_hub import Product, ProductAsset, ProductVariant, PrintRule
from xw_office.models.settings_kv import SettingKV
from xw_office.print_center.models import PrintArticle, PrintStep
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.products.catalog import ProductCatalogService, _UNRELEASED_DYNAMIC_SKUS


class LegacyProduct(BaseModel):
    sku: str
    name: str = ""
    is_digital: bool = False
    title_print_configs: dict[str, dict[str, object]] = Field(default_factory=dict)


class OfficialCatalogue:
    """Deliberately exposes only a list operation; PostgreSQL reads are read-only."""

    def __init__(self, sessions: sessionmaker[Session], *, prefer_hub: bool = False) -> None:
        self._sessions = sessions
        self._prefer_hub = prefer_hub

    def list_articles(self) -> list[PrintArticle]:
        with self._sessions() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
            raw = session.scalar(
                select(SettingKV.value_json).where(SettingKV.key == "inventory.products")
            ) or "[]"
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
                        id=article_id, source="official", sku=sku,
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
                    Product.active.is_(True), ProductVariant.active.is_(True),
                    Product.product_type != "digital",
                )
            ).all()
            assets = list(session.scalars(
                select(ProductAsset).where(
                    ProductAsset.role == "PRINT_PDF",
                    ProductAsset.storage_kind.in_(("NETWORK_PATH", "ONEDRIVE")),
                ).order_by(ProductAsset.sort_order, ProductAsset.id)
            ))
            for product, variant, rule in hub_rows:
                sku = variant.sku.strip().upper()
                if sku in _UNRELEASED_DYNAMIC_SKUS:
                    continue
                article_id = f"office:{sku}:"
                if article_id in articles and not self._prefer_hub:
                    continue
                matching_assets = [a for a in assets if a.product_id == product.id
                                   and a.variant_id in (None, variant.id)]
                asset = next(
                    (a for a in matching_assets if a.variant_id == variant.id),
                    matching_assets[0] if matching_assets else None,
                )
                articles[article_id] = PrintArticle(
                    id=article_id, source="official", sku=sku,
                    name=variant.name or product.name,
                    pdf_path=resolve_shared_path(asset.uri if asset else ""),
                    profile_id=rule.print_profile_id or "" if rule else "",
                    print_plan=TypeAdapter(tuple[PrintStep, ...]).validate_python(
                        rule.print_plan or [] if rule else []
                    ),
                )
            return sorted(articles.values(), key=lambda article: (article.name.casefold(), article.id))
