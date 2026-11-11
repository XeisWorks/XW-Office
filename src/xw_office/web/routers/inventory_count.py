"""Guided inventory count API."""
from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response, status

from xw_office.services.product_hub.inventory_count import InventoryCountService, InventoryCountView
from xw_office.web.schemas.inventory import (
    InventoryCountConfirmRequest,
    InventoryCountLineOut,
    InventoryCountOut,
    InventoryCountRecordRequest,
)


def build_inventory_count_router(
    get_service: Callable[[], InventoryCountService],
    require_edit_enabled: Callable[[], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/inventory/counts", tags=["product-hub-inventory-count"])

    def output(view: InventoryCountView) -> InventoryCountOut:
        return InventoryCountOut(
            id=view.id, status=view.status, location_code=view.location_code,
            started_at=view.started_at, confirmed_at=view.confirmed_at,
            baseline_source_hash=view.baseline_source_hash,
            lines=[InventoryCountLineOut(**line.__dict__) for line in view.lines],
        )

    @router.post("", response_model=InventoryCountOut, status_code=status.HTTP_201_CREATED)
    def start_count(service: InventoryCountService = Depends(get_service)) -> InventoryCountOut:
        return output(service.start())

    @router.get("/{count_id}/export.csv")
    def export_count_csv(
        count_id: uuid.UUID,
        service: InventoryCountService = Depends(get_service),
    ) -> Response:
        try:
            view = service.get(count_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(
            [
                "SKU",
                "Titel",
                "Lagerort",
                "Systembestand",
                "Gezählt",
                "Differenz",
                "Status",
                "Notiz",
                "Bewegungs-ID",
            ]
        )
        for line in view.lines:
            writer.writerow(
                [
                    line.sku,
                    line.title,
                    line.location_code,
                    line.system_quantity,
                    "" if line.counted_quantity is None else line.counted_quantity,
                    "" if line.difference is None else line.difference,
                    line.status,
                    line.note,
                    "" if line.movement_id is None else str(line.movement_id),
                ]
            )
        return Response(
            content="\ufeff" + buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="inventur-{count_id}.csv"'},
        )

    @router.get("/{count_id}", response_model=InventoryCountOut)
    def get_count(count_id: uuid.UUID, service: InventoryCountService = Depends(get_service)) -> InventoryCountOut:
        try:
            return output(service.get(count_id))
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.put("/{count_id}/lines/{line_id}", response_model=InventoryCountLineOut, dependencies=[Depends(require_edit_enabled)])
    def record_line(
        count_id: uuid.UUID,
        line_id: uuid.UUID,
        body: InventoryCountRecordRequest,
        service: InventoryCountService = Depends(get_service),
    ) -> InventoryCountLineOut:
        try:
            line = service.record_count(count_id=count_id, line_id=line_id, counted_quantity=body.counted_quantity, note=body.note)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return InventoryCountLineOut(**line.__dict__)

    @router.post("/{count_id}/confirm", response_model=InventoryCountOut, dependencies=[Depends(require_edit_enabled)])
    def confirm_count(
        count_id: uuid.UUID,
        body: InventoryCountConfirmRequest,
        service: InventoryCountService = Depends(get_service),
    ) -> InventoryCountOut:
        try:
            return output(service.confirm(count_id=count_id, actor=body.actor))
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return router


__all__ = ["build_inventory_count_router"]
