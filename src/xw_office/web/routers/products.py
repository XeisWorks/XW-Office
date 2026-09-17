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
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from xw_office.models.product_hub import Product
from xw_office.repositories.product_hub import OptimisticLockError, ProductFilter, ProductHubRepository
from xw_office.services.product_hub.editing import EditingService, UnknownFieldError
from xw_office.services.product_hub.readiness import build_readiness_summary, evaluate_product_readiness
from xw_office.web.schemas.products import (
    AssetUpdateRequest,
    AuditLogOut,
    ChannelMappingOut,
    EditionCreateRequest,
    EditionOut,
    IdentifierAddRequest,
    IdentifierOut,
    ImprovementCreateRequest,
    ImprovementUpdateRequest,
    Page,
    PriceOut,
    PriceSetRequest,
    PrintRuleOut,
    PrintRuleUpsertRequest,
    ProductAssetOut,
    ProductDetail,
    ProductImprovementOut,
    ProductListItem,
    ProductReadinessOut,
    ProductUpdateRequest,
    ProductVariantOut,
    ReadinessSummaryOut,
    TagAddRequest,
    TagOut,
    VariantUpdateRequest,
)

RepoDependency = Callable[[], Generator[ProductHubRepository, None, None]]
EditingDependency = Callable[[], EditingService]
EditGateDependency = Callable[[], None]


def build_products_router(
    get_repo: RepoDependency,
    get_editing: EditingDependency,
    require_edit_enabled: EditGateDependency,
) -> APIRouter:
    """Build the products router, parameterized by a repo + editing-service dependency.

    Mirrors ``create_app(settings)``'s own injection style so tests can pass a
    SQLite-backed repo and Railway gets one bound to the real Postgres session.

    Every PATCH/POST/PUT/DELETE route is registered on ``write_router`` and only
    mounted with ``require_edit_enabled`` applied — a separate kill switch from the
    read API's, since this is the first write-capable surface this service exposes
    (see ``ContentWebSettings.product_hub_edit_enabled``, defaults to off).
    """
    router = APIRouter(prefix="/api/v1", tags=["product-hub"])
    write_router = APIRouter()

    def _get_product_or_404(repo: ProductHubRepository, product_id: uuid.UUID) -> Product:
        product = repo.get_product(product_id)
        if product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        return product

    def _conflict(current: object, out_schema: type[BaseModel]) -> HTTPException:
        """409 body carries the current server state, per the build plan's
        "Konflikt -> HTTP 409 mit aktuellem Serverstand" — the client can show a diff
        or just overwrite its local copy instead of blindly retrying."""
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=jsonable_encoder(out_schema.model_validate(current)),
        )

    @router.get("/products", response_model=Page[ProductListItem])
    def list_products(
        search: str | None = Query(default=None),
        product_status: str | None = Query(default=None, alias="status"),
        active: bool | None = Query(default=None),
        family_id: uuid.UUID | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=2000),
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

    @write_router.patch("/products/{product_id}", response_model=ProductDetail)
    def patch_product(
        product_id: uuid.UUID,
        body: ProductUpdateRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> ProductDetail:
        _get_product_or_404(repo, product_id)
        changes = body.model_dump(exclude={"expected_row_version"}, exclude_unset=True)
        try:
            updated = editing.update_product(
                product_id, expected_row_version=body.expected_row_version, changes=changes
            )
        except OptimisticLockError:
            raise _conflict(_get_product_or_404(repo, product_id), ProductDetail) from None
        except UnknownFieldError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return ProductDetail.model_validate(updated)

    @router.get("/products/{product_id}/variants", response_model=list[ProductVariantOut])
    def get_product_variants(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[ProductVariantOut]:
        _get_product_or_404(repo, product_id)
        return [ProductVariantOut.model_validate(v) for v in repo.list_variants(product_id)]

    @write_router.patch("/products/{product_id}/variants/{variant_id}", response_model=ProductVariantOut)
    def patch_product_variant(
        product_id: uuid.UUID,
        variant_id: uuid.UUID,
        body: VariantUpdateRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> ProductVariantOut:
        _get_product_or_404(repo, product_id)
        changes = body.model_dump(exclude={"expected_row_version"}, exclude_unset=True)
        try:
            updated = editing.update_variant(
                variant_id, expected_row_version=body.expected_row_version, changes=changes
            )
        except OptimisticLockError:
            current = repo.get_variant(variant_id)
            if current is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found") from None
            raise _conflict(current, ProductVariantOut) from None
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except UnknownFieldError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return ProductVariantOut.model_validate(updated)

    @router.get(
        "/products/{product_id}/variants/{variant_id}/prices", response_model=list[PriceOut]
    )
    def get_variant_prices(
        product_id: uuid.UUID, variant_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[PriceOut]:
        _get_product_or_404(repo, product_id)
        return [PriceOut.model_validate(p) for p in repo.list_prices(variant_id)]

    @write_router.post(
        "/products/{product_id}/variants/{variant_id}/prices",
        response_model=PriceOut,
        status_code=status.HTTP_201_CREATED,
    )
    def set_variant_price(
        product_id: uuid.UUID,
        variant_id: uuid.UUID,
        body: PriceSetRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> PriceOut:
        _get_product_or_404(repo, product_id)
        try:
            price = editing.set_price(
                variant_id,
                price_list_code=body.price_list_code,
                currency=body.currency,
                net_amount=body.net_amount,
                gross_amount=body.gross_amount,
                tax_rate=body.tax_rate,
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return PriceOut.model_validate(price)

    @router.get(
        "/products/{product_id}/variants/{variant_id}/print-rule",
        response_model=PrintRuleOut,
    )
    def get_variant_print_rule(
        product_id: uuid.UUID, variant_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> PrintRuleOut:
        _get_product_or_404(repo, product_id)
        rule = repo.get_print_rule(variant_id)
        if rule is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Print rule not set")
        return PrintRuleOut.model_validate(rule)

    @write_router.put(
        "/products/{product_id}/variants/{variant_id}/print-rule",
        response_model=PrintRuleOut,
    )
    def upsert_variant_print_rule(
        product_id: uuid.UUID,
        variant_id: uuid.UUID,
        body: PrintRuleUpsertRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> PrintRuleOut:
        _get_product_or_404(repo, product_id)
        changes = body.model_dump(exclude={"expected_row_version"}, exclude_unset=True)
        try:
            updated = editing.upsert_print_rule(
                variant_id, expected_row_version=body.expected_row_version, changes=changes
            )
        except OptimisticLockError:
            current = repo.get_print_rule(variant_id)
            if current is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Print rule was removed concurrently"
                ) from None
            raise _conflict(current, PrintRuleOut) from None
        except UnknownFieldError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return PrintRuleOut.model_validate(updated)

    @router.get("/products/{product_id}/assets", response_model=list[ProductAssetOut])
    def get_product_assets(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[ProductAssetOut]:
        _get_product_or_404(repo, product_id)
        return [ProductAssetOut.model_validate(a) for a in repo.list_assets(product_id)]

    @write_router.patch("/products/{product_id}/assets/{asset_id}", response_model=ProductAssetOut)
    def patch_product_asset(
        product_id: uuid.UUID,
        asset_id: uuid.UUID,
        body: AssetUpdateRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> ProductAssetOut:
        _get_product_or_404(repo, product_id)
        changes = body.model_dump(exclude={"expected_row_version"}, exclude_unset=True)
        try:
            updated = editing.update_asset(
                asset_id, expected_row_version=body.expected_row_version, changes=changes
            )
        except OptimisticLockError:
            current = repo.get_asset(asset_id)
            if current is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found") from None
            raise _conflict(current, ProductAssetOut) from None
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except UnknownFieldError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return ProductAssetOut.model_validate(updated)

    @router.get("/products/{product_id}/tags", response_model=list[TagOut])
    def get_product_tags(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[TagOut]:
        _get_product_or_404(repo, product_id)
        links = repo.list_product_tags(product_id)
        tags = [repo.get_tag(link.tag_id) for link in links]
        return [TagOut.model_validate(t) for t in tags if t is not None]

    @write_router.post(
        "/products/{product_id}/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED
    )
    def add_product_tag(
        product_id: uuid.UUID,
        body: TagAddRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> TagOut:
        _get_product_or_404(repo, product_id)
        try:
            tag = editing.add_tag(product_id, tag_code=body.tag_code)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return TagOut.model_validate(tag)

    @write_router.delete(
        "/products/{product_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    def remove_product_tag(
        product_id: uuid.UUID,
        tag_id: uuid.UUID,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> None:
        _get_product_or_404(repo, product_id)
        editing.remove_tag(product_id, tag_id=tag_id)

    @router.get("/products/{product_id}/identifiers", response_model=list[IdentifierOut])
    def get_product_identifiers(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[IdentifierOut]:
        _get_product_or_404(repo, product_id)
        return [IdentifierOut.model_validate(i) for i in repo.list_identifiers(product_id=product_id)]

    @write_router.post(
        "/products/{product_id}/identifiers",
        response_model=IdentifierOut,
        status_code=status.HTTP_201_CREATED,
    )
    def add_product_identifier(
        product_id: uuid.UUID,
        body: IdentifierAddRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> IdentifierOut:
        _get_product_or_404(repo, product_id)
        identifier = editing.add_identifier(
            product_id,
            scheme=body.scheme,
            value=body.value,
            variant_id=body.variant_id,
            market=body.market,
            is_primary=body.is_primary,
        )
        return IdentifierOut.model_validate(identifier)

    @write_router.delete(
        "/products/{product_id}/identifiers/{identifier_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_product_identifier(
        product_id: uuid.UUID,
        identifier_id: uuid.UUID,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> None:
        _get_product_or_404(repo, product_id)
        try:
            editing.remove_identifier(product_id, identifier_id=identifier_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.get("/products/{product_id}/improvements", response_model=list[ProductImprovementOut])
    def get_product_improvements(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[ProductImprovementOut]:
        _get_product_or_404(repo, product_id)
        return [ProductImprovementOut.model_validate(i) for i in repo.list_improvements(product_id)]

    @write_router.post(
        "/products/{product_id}/improvements",
        response_model=ProductImprovementOut,
        status_code=status.HTTP_201_CREATED,
    )
    def add_product_improvement(
        product_id: uuid.UUID,
        body: ImprovementCreateRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> ProductImprovementOut:
        _get_product_or_404(repo, product_id)
        improvement = editing.create_improvement(
            product_id,
            description=body.description,
            variant_id=body.variant_id,
            title=body.title,
            severity=body.severity,
        )
        return ProductImprovementOut.model_validate(improvement)

    @write_router.patch(
        "/products/{product_id}/improvements/{improvement_id}",
        response_model=ProductImprovementOut,
    )
    def patch_product_improvement(
        product_id: uuid.UUID,
        improvement_id: uuid.UUID,
        body: ImprovementUpdateRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> ProductImprovementOut:
        _get_product_or_404(repo, product_id)
        changes = body.model_dump(exclude={"expected_row_version"}, exclude_unset=True)
        try:
            updated = editing.update_improvement(
                improvement_id, expected_row_version=body.expected_row_version, changes=changes
            )
        except OptimisticLockError:
            current = repo.get_improvement(improvement_id)
            if current is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Improvement not found"
                ) from None
            raise _conflict(current, ProductImprovementOut) from None
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except UnknownFieldError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return ProductImprovementOut.model_validate(updated)

    @router.get("/products/{product_id}/editions", response_model=list[EditionOut])
    def get_product_editions(
        product_id: uuid.UUID, repo: ProductHubRepository = Depends(get_repo)
    ) -> list[EditionOut]:
        _get_product_or_404(repo, product_id)
        return [EditionOut.model_validate(e) for e in repo.list_editions(product_id)]

    @write_router.post(
        "/products/{product_id}/editions",
        response_model=EditionOut,
        status_code=status.HTTP_201_CREATED,
    )
    def add_product_edition(
        product_id: uuid.UUID,
        body: EditionCreateRequest,
        repo: ProductHubRepository = Depends(get_repo),
        editing: EditingService = Depends(get_editing),
    ) -> EditionOut:
        _get_product_or_404(repo, product_id)
        edition = editing.create_edition(
            product_id,
            label=body.label,
            edition_number=body.edition_number,
            notes=body.notes,
            resolve_improvement_ids=body.resolve_improvement_ids,
        )
        return EditionOut.model_validate(edition)

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

    router.include_router(write_router, dependencies=[Depends(require_edit_enabled)])
    return router
