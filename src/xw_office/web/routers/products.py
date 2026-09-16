"""Product Hub Read API (PR07): stable read-only endpoints for XW-Office Desktop
and a future WebUI.

Auth is applied where this router is *included* (``web/app.py``), not here — this
module only defines routes and stays independent of the app-level bootstrap-token
wiring, matching this project's existing ``create_app(settings)`` factory style.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Generator

from fastapi import APIRouter, Depends, HTTPException, Query, status

from xw_office.models.product_hub import Product
from xw_office.repositories.product_hub import ProductFilter, ProductHubRepository
from xw_office.services.product_hub.readiness import build_readiness_summary, evaluate_product_readiness
from xw_office.web.schemas.products import (
    AuditLogOut,
    ChannelMappingOut,
    Page,
    ProductAssetOut,
    ProductDetail,
    ProductImprovementOut,
    ProductListItem,
    ProductReadinessOut,
    ProductVariantOut,
    ReadinessSummaryOut,
)

RepoDependency = Callable[[], Generator[ProductHubRepository, None, None]]


def build_products_router(get_repo: RepoDependency) -> APIRouter:
    """Build the products router, parameterized by a repo dependency.

    Mirrors ``create_app(settings)``'s own injection style so tests can pass a
    SQLite-backed repo and Railway gets one bound to the real Postgres session.
    """
    router = APIRouter(prefix="/api/v1", tags=["product-hub"])

    def _get_product_or_404(repo: ProductHubRepository, product_id: uuid.UUID) -> Product:
        product = repo.get_product(product_id)
        if product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        return product

    @router.get("/products", response_model=Page[ProductListItem])
    def list_products(
        search: str | None = Query(default=None),
        product_status: str | None = Query(default=None, alias="status"),
        active: bool | None = Query(default=None),
        family_id: uuid.UUID | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        repo: ProductHubRepository = Depends(get_repo),
    ) -> Page[ProductListItem]:
        base_filters = ProductFilter(
            status=product_status, active=active, family_id=family_id, search=search
        )
        total = repo.count_products(base_filters)
        page_filters = ProductFilter(
            status=product_status,
            active=active,
            family_id=family_id,
            search=search,
            limit=limit,
            offset=offset,
        )
        items = [ProductListItem.model_validate(p) for p in repo.list_products(page_filters)]
        return Page(items=items, total=total, limit=limit, offset=offset)

    @router.get("/products/by-sku/{sku}", response_model=ProductDetail)
    def get_product_by_sku(sku: str, repo: ProductHubRepository = Depends(get_repo)) -> ProductDetail:
        product = repo.get_product_by_sku(sku)
        if product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        return ProductDetail.model_validate(product)

    @router.get("/products/{product_id}", response_model=ProductDetail)
    def get_product(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> ProductDetail:
        return ProductDetail.model_validate(_get_product_or_404(repo, product_id))

    @router.get("/products/{product_id}/variants", response_model=list[ProductVariantOut])
    def get_product_variants(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[ProductVariantOut]:
        _get_product_or_404(repo, product_id)
        return [ProductVariantOut.model_validate(v) for v in repo.list_variants(product_id)]

    @router.get("/products/{product_id}/assets", response_model=list[ProductAssetOut])
    def get_product_assets(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[ProductAssetOut]:
        _get_product_or_404(repo, product_id)
        return [ProductAssetOut.model_validate(a) for a in repo.list_assets(product_id)]

    @router.get("/products/{product_id}/improvements", response_model=list[ProductImprovementOut])
    def get_product_improvements(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[ProductImprovementOut]:
        _get_product_or_404(repo, product_id)
        return [ProductImprovementOut.model_validate(i) for i in repo.list_improvements(product_id)]

    @router.get("/products/{product_id}/channels", response_model=list[ChannelMappingOut])
    def get_product_channels(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[ChannelMappingOut]:
        _get_product_or_404(repo, product_id)
        mappings = repo.list_channel_mappings(entity_type="product", internal_entity_id=product_id)
        return [ChannelMappingOut.model_validate(m) for m in mappings]

    @router.get("/products/{product_id}/audit", response_model=list[AuditLogOut])
    def get_product_audit(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[AuditLogOut]:
        _get_product_or_404(repo, product_id)
        return [AuditLogOut.model_validate(a) for a in repo.list_audit_log("product", product_id)]

    @router.get("/products/{product_id}/readiness", response_model=ProductReadinessOut)
    def get_product_readiness(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> ProductReadinessOut:
        product = _get_product_or_404(repo, product_id)
        return ProductReadinessOut.model_validate(evaluate_product_readiness(repo, product))

    @router.get("/catalog/readiness-summary", response_model=ReadinessSummaryOut)
    def get_readiness_summary(
        repo: ProductHubRepository = Depends(get_repo),
    ) -> ReadinessSummaryOut:
        products = repo.list_products()
        return ReadinessSummaryOut.model_validate(build_readiness_summary(repo, products))

    return router
