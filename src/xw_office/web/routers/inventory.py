"""Inventory V2 shadow-mode API (PR13/PR14).

Auth is applied where this router is *included* (``web/app.py``), matching the other
Product Hub routers' convention. Read routes (summary/alerts/stock/movements-list)
only need the read gate; movement-recording/threshold/reconcile routes additionally
require the edit gate, same reasoning as the products edit API — they write.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Generator

from fastapi import APIRouter, Depends, HTTPException, status

from xw_office.repositories.product_hub_inventory import InventoryRepository, NegativeStockError
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.web.schemas.inventory import (
    InventoryAlertOut,
    InventorySummaryOut,
    MovementCreateRequest,
    MovementOut,
    MovementResultOut,
    ReconcileRequest,
    ReconcileResponse,
    StockOut,
    ThresholdUpdateRequest,
)

InventoryRepoDependency = Callable[[], Generator[InventoryRepository, None, None]]
InventoryServiceDependency = Callable[[], InventoryV2Service]
EditGateDependency = Callable[[], None]


def build_inventory_router(
    get_repo: InventoryRepoDependency,
    get_service: InventoryServiceDependency,
    require_edit_enabled: EditGateDependency,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/inventory", tags=["product-hub-inventory"])
    write_router = APIRouter()

    @router.get("/summary", response_model=InventorySummaryOut)
    def get_summary(service: InventoryV2Service = Depends(get_service)) -> InventorySummaryOut:
        summary = service.compute_summary()
        return InventorySummaryOut(
            physical_products=summary.physical_products,
            low_stock=summary.low_stock,
            out_of_stock=summary.out_of_stock,
            open_reprint_alerts=summary.open_reprint_alerts,
            sync_errors=summary.sync_errors,
            updated_at=summary.updated_at,
        )

    @router.get("/alerts", response_model=list[InventoryAlertOut])
    def list_alerts(repo: InventoryRepository = Depends(get_repo)) -> list[InventoryAlertOut]:
        return [InventoryAlertOut.model_validate(a) for a in repo.list_open_alerts()]

    @router.get("/variants/{variant_id}/stock", response_model=list[StockOut])
    def get_variant_stock(
        variant_id: uuid.UUID, repo: InventoryRepository = Depends(get_repo)
    ) -> list[StockOut]:
        out: list[StockOut] = []
        for location in repo.list_locations():
            stock = repo.get_stock(variant_id, location.id)
            if stock is not None:
                out.append(StockOut.model_validate(stock))
        return out

    @router.get("/variants/{variant_id}/movements", response_model=list[MovementOut])
    def get_variant_movements(
        variant_id: uuid.UUID,
        location_code: str = "MAIN",
        repo: InventoryRepository = Depends(get_repo),
    ) -> list[MovementOut]:
        location = repo.get_location_by_code(location_code)
        if location is None:
            return []
        return [MovementOut.model_validate(m) for m in repo.list_movements(variant_id, location.id)]

    @write_router.post(
        "/movements", response_model=MovementResultOut, status_code=status.HTTP_201_CREATED
    )
    def record_movement(
        body: MovementCreateRequest, service: InventoryV2Service = Depends(get_service)
    ) -> MovementResultOut:
        try:
            result = service.record_movement(
                variant_id=body.variant_id,
                delta=body.delta,
                reason=body.reason,
                source=body.source,
                idempotency_key=body.idempotency_key,
                location_code=body.location_code,
                external_reference=body.external_reference,
                note=body.note,
            )
        except NegativeStockError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return MovementResultOut(
            movement=MovementOut.model_validate(result.movement),
            alert_opened=result.alert_opened.id if result.alert_opened is not None else None,
        )

    @write_router.put("/variants/{variant_id}/thresholds", response_model=StockOut)
    def set_thresholds(
        variant_id: uuid.UUID,
        body: ThresholdUpdateRequest,
        repo: InventoryRepository = Depends(get_repo),
    ) -> StockOut:
        location = repo.get_or_create_location(code=body.location_code, name="Hauptlager")
        stock = repo.set_stock_thresholds(
            variant_id,
            location.id,
            reorder_point=body.reorder_point,
            target_stock=body.target_stock,
            default_reprint_qty=body.default_reprint_qty,
        )
        return StockOut.model_validate(stock)

    @write_router.post("/reconcile", response_model=ReconcileResponse)
    def reconcile(
        body: ReconcileRequest, service: InventoryV2Service = Depends(get_service)
    ) -> ReconcileResponse:
        drift = service.reconcile_variant_stock(
            body.variant_id,
            sevdesk_on_hand=body.sevdesk_on_hand,
            location_code=body.location_code,
        )
        return ReconcileResponse(drift_detected=drift)

    @write_router.post("/alerts/{alert_id}/resolve", response_model=InventoryAlertOut)
    def resolve_alert(
        alert_id: uuid.UUID, repo: InventoryRepository = Depends(get_repo)
    ) -> InventoryAlertOut:
        try:
            alert = repo.resolve_alert(alert_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return InventoryAlertOut.model_validate(alert)

    router.include_router(write_router, dependencies=[Depends(require_edit_enabled)])
    return router
