"""Authenticated private cover-template configuration API."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from xw_office.services.product_hub.cover_templates import CoverPreviewRequest, CoverTemplateService


class CoverTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: str
    name: str
    etag: str
    size: int


class CoverFontReadinessOut(BaseModel):
    available_families: list[str]
    missing_families: list[str]
    export_ready: bool


class CoverConfigurationOut(BaseModel):
    output_width_px: int
    output_height_px: int
    output_format: str
    preserve_aspect_ratio: bool
    required_families: list[str]


class CoverPreviewIn(BaseModel):
    """Text only; clients never send private backgrounds or font material."""

    template_id: str = Field(min_length=1, max_length=256)
    composer: str = Field(default="", max_length=250)
    title: str = Field(default="", max_length=250)
    arranger: str = Field(default="", max_length=250)
    edition: str = Field(default="", max_length=100)


CoverServiceDependency = Callable[[], CoverTemplateService]


def build_covers_router(get_cover_service: CoverServiceDependency) -> APIRouter:
    router = APIRouter(prefix="/api/v1/covers", tags=["product-hub-covers"])

    @router.get("/configuration", response_model=CoverConfigurationOut)
    def configuration(service: CoverTemplateService = Depends(get_cover_service)) -> CoverConfigurationOut:
        try:
            spec = service.render_spec
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return CoverConfigurationOut(
            output_width_px=spec.output_width_px,
            output_height_px=spec.output_height_px,
            output_format=spec.output_format,
            preserve_aspect_ratio=spec.preserve_aspect_ratio,
            required_families=list(spec.required_families),
        )

    @router.get("/templates", response_model=list[CoverTemplateOut])
    def list_templates(service: CoverTemplateService = Depends(get_cover_service)) -> list[CoverTemplateOut]:
        try:
            return [CoverTemplateOut.model_validate(item) for item in service.list_templates()]
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    @router.get("/templates/{template_id}/thumbnail")
    def template_thumbnail(template_id: str, service: CoverTemplateService = Depends(get_cover_service)) -> Response:
        try:
            content = service.thumbnail(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return Response(content=content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})

    @router.get("/font-readiness", response_model=CoverFontReadinessOut)
    def font_readiness(service: CoverTemplateService = Depends(get_cover_service)) -> CoverFontReadinessOut:
        try:
            result = service.font_readiness()
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return CoverFontReadinessOut(
            available_families=list(result.available_families),
            missing_families=list(result.missing_families), export_ready=result.export_ready,
        )

    @router.post("/preview")
    def cover_preview(
        request: CoverPreviewIn, service: CoverTemplateService = Depends(get_cover_service)
    ) -> Response:
        try:
            preview = service.render_preview(CoverPreviewRequest(**request.model_dump()))
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        return Response(
            content=preview.content,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, no-store"},
        )
    return router
