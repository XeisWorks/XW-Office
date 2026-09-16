"""Dealer sharing admin API (PR12): create/list/revoke shares.

Auth is applied where this router is *included* (``web/app.py``), matching the other
Product Hub routers' convention.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, status

from xw_office.services.product_hub.sharing import InvalidFieldWhitelistError, SharingService
from xw_office.web.schemas.sharing import ShareCreatedOut, ShareCreateRequest, ShareOut

SharingDependency = Callable[[], SharingService]


def build_sharing_admin_router(get_sharing: SharingDependency, *, public_base_url: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1/shares", tags=["product-hub-sharing"])

    @router.post("", response_model=ShareCreatedOut, status_code=status.HTTP_201_CREATED)
    def create_share(body: ShareCreateRequest) -> ShareCreatedOut:
        service = get_sharing()
        try:
            share, token = service.create_share(
                title=body.title,
                field_whitelist=body.field_whitelist,
                price_list_code=body.price_list_code,
                allow_csv=body.allow_csv,
                allow_xlsx=body.allow_xlsx,
                allow_images=body.allow_images,
                expires_at=body.expires_at,
            )
        except InvalidFieldWhitelistError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        base = ShareOut.model_validate(share)
        return ShareCreatedOut(
            **base.model_dump(), token=token, share_url=f"{public_base_url}/share/{token}"
        )

    @router.get("", response_model=list[ShareOut])
    def list_shares() -> list[ShareOut]:
        return [ShareOut.model_validate(s) for s in get_sharing().list_shares()]

    @router.post("/{share_id}/revoke", response_model=ShareOut)
    def revoke_share(share_id: uuid.UUID) -> ShareOut:
        try:
            share = get_sharing().revoke(share_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return ShareOut.model_validate(share)

    return router
