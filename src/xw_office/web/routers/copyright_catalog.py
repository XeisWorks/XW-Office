"""Narrow, read-only Product Hub snapshot for XW-Flow copyright discovery."""

from collections.abc import Callable, Generator
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from xw_office.repositories.product_hub import ProductHubRepository

RepoDependency = Callable[[], Generator[ProductHubRepository, None, None]]

_BRAND_ALIASES = {
    "mnozil brass": "Mnozil Brass",
    "da blechhauf'n": "da Blechhauf'n",
    "da blechhaufn": "da Blechhauf'n",
    "thomas gansch": "Thomas Gansch",
    "blasmusik supergroup": "Blasmusik Supergroup",
    "wüdaramusi": "WüdaraMusi",
    "wuedaramusi": "WüdaraMusi",
    "musikheroes": "MusikHeroes",
}


class CatalogVariant(BaseModel):
    variant_id: str
    sku: str
    updated_at: datetime


class CatalogEdition(BaseModel):
    edition_id: str
    label: str
    updated_at: datetime


class CatalogProduct(BaseModel):
    product_id: str
    title: str
    brand: str
    slug: str
    sku: str
    updated_at: datetime
    variants: list[CatalogVariant]
    editions: list[CatalogEdition]


class CatalogSnapshot(BaseModel):
    schema_version: int = 1
    products: list[CatalogProduct]


def _brand(raw: str | None, attributes: dict[str, object]) -> str | None:
    candidates: list[object] = [raw]
    music = attributes.get("music_attributes")
    if isinstance(music, dict):
        candidates.extend([music.get("series"), music.get("brand")])
    for candidate in candidates:
        if isinstance(candidate, str):
            canonical = _BRAND_ALIASES.get(candidate.strip().casefold())
            if canonical:
                return canonical
    return None


def build_copyright_catalog_router(get_repo: RepoDependency) -> APIRouter:
    router = APIRouter(prefix="/api/v1/copyright", tags=["copyright-catalog"])

    @router.get("/catalog", response_model=CatalogSnapshot)
    def catalog(repo: ProductHubRepository = Depends(get_repo)) -> CatalogSnapshot:
        products = repo.list_products()
        selected = [
            (product, _brand(product.brand_name, product.attributes or {})) for product in products
        ]
        selected = [(product, brand) for product, brand in selected if brand is not None]
        variants_by_product: dict[str, list[CatalogVariant]] = {}
        ids = [product.id for product, _ in selected]
        if ids:
            for variant in repo.list_variants_for_products(ids):
                variants_by_product.setdefault(str(variant.product_id), []).append(
                    CatalogVariant(
                        variant_id=str(variant.id), sku=variant.sku, updated_at=variant.updated_at
                    )
                )
        rows = []
        for product, brand in selected:
            editions = [
                CatalogEdition(
                    edition_id=str(item.id), label=item.label, updated_at=item.updated_at
                )
                for item in repo.list_editions(product.id)
            ]
            rows.append(
                CatalogProduct(
                    product_id=str(product.id),
                    title=product.name,
                    brand=brand,
                    slug=product.slug,
                    sku=product.sku,
                    updated_at=product.updated_at,
                    variants=variants_by_product.get(str(product.id), []),
                    editions=editions,
                )
            )
        return CatalogSnapshot(products=rows)

    return router
