"""Inventory alert detail/task API."""
from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status

from xw_office.services.mailing.service import MailDeliveryService
from xw_office.services.product_hub.inventory_alert_tasks import InventoryAlertTaskService
from xw_office.web.schemas.inventory import InventoryAlertTaskOut, InventoryAlertTaskRequest


def build_inventory_alert_task_router(
    get_service: Callable[[], InventoryAlertTaskService],
    get_mail_delivery: Callable[[], MailDeliveryService],
    require_edit_enabled: Callable[[], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/inventory/alerts", tags=["product-hub-inventory-alerts"])

    @router.post("/{alert_id}/task", response_model=InventoryAlertTaskOut, dependencies=[Depends(require_edit_enabled)])
    def create_task(
        alert_id: uuid.UUID,
        body: InventoryAlertTaskRequest,
        service: InventoryAlertTaskService = Depends(get_service),
        mail_delivery: MailDeliveryService = Depends(get_mail_delivery),
    ) -> InventoryAlertTaskOut:
        try:
            result = service.create_and_send(
                alert_id,
                mail_delivery=mail_delivery,
                sales_average_monthly=body.sales_average_monthly,
                three_month_demand=body.three_month_demand,
                data_window=body.data_window,
                explicit_resend=body.explicit_resend,
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return InventoryAlertTaskOut(
            alert_id=result.alert_id, task_id=result.task_id, status=result.status,
            recipient=result.recipient, subject=result.subject, error=result.error,
        )

    return router


__all__ = ["build_inventory_alert_task_router"]
