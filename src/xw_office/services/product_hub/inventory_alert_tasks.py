"""Manual, deduplicated Graph task creation for open inventory alerts."""
from __future__ import annotations

from dataclasses import dataclass
import datetime
import uuid

from sqlalchemy import select

from xw_office.core.database import session_scope
from xw_office.models.inventory_alert_task import InventoryAlertTask
from xw_office.models.product_hub import Product, ProductVariant
from xw_office.models.product_hub_inventory import InventoryAlert, InventoryLocation, InventoryStock


@dataclass(frozen=True)
class InventoryAlertTaskResult:
    alert_id: uuid.UUID
    task_id: uuid.UUID
    status: str
    recipient: str
    subject: str
    body: str
    error: str = ""


class InventoryAlertTaskService:
    """Render and send exactly one task mail per alert unless explicitly retried."""

    RECIPIENT = "todo@xeisworks.at"

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def create_and_send(
        self,
        alert_id: uuid.UUID,
        *,
        mail_delivery,
        sales_average_monthly: float | None = None,
        three_month_demand: int | None = None,
        data_window: str = "bis zu 60 vollständige Monate",
        explicit_resend: bool = False,
    ) -> InventoryAlertTaskResult:
        with session_scope(self._session_factory) as session:
            # Serialize task creation per alert on PostgreSQL.  A repeated click
            # therefore observes the already-sent row instead of racing a second mail.
            alert = session.get(InventoryAlert, alert_id, with_for_update=True)
            if alert is None:
                raise KeyError(f"Inventory alert {alert_id} nicht gefunden")
            existing = session.scalar(
                select(InventoryAlertTask)
                .where(InventoryAlertTask.alert_id == alert_id)
                .with_for_update()
            )
            if existing is not None and existing.status == "sent" and not explicit_resend:
                return self._result(existing)
            variant = session.get(ProductVariant, alert.variant_id)
            product = session.get(Product, variant.product_id) if variant is not None else None
            location = session.get(InventoryLocation, alert.location_id)
            stock = session.get(InventoryStock, (alert.variant_id, alert.location_id))
            sku = str(variant.sku if variant is not None else "unbekannt")
            title = str((variant.name if variant is not None else "") or (product.name if product is not None else sku))
            on_hand = int(stock.on_hand if stock is not None else alert.observed_stock or 0)
            threshold = int(alert.threshold if alert.threshold is not None else 0)
            if sales_average_monthly is None and stock is not None:
                sales_average_monthly = max(0, int(stock.automatic_reorder_point or 0)) / 3
            if three_month_demand is None and stock is not None:
                three_month_demand = int(stock.automatic_reorder_point or 0)
            average_text = "unbekannt" if sales_average_monthly is None else f"{sales_average_monthly:.2f} Stk/Monat"
            demand_text = "unbekannt" if three_month_demand is None else f"{three_month_demand} Stk"
            subject = f"Lageralarm: {sku} – {title}"
            product_link = f"/app/products/{product.id}" if product is not None else "nicht verfügbar"
            body = (
                "Lageralarm aus XW-Office\n\n"
                f"Alarm-ID: {alert.id}\nSKU: {sku}\nProdukttitel: {title}\n"
                f"Lagerort: {location.code if location is not None else 'unbekannt'}\n"
                f"Ist-Bestand: {on_hand}\nAlarmbestand: {threshold}\n"
                f"Durchschnittlicher Monatsverkauf: {average_text}\n"
                f"Drei-Monats-Bedarf: {demand_text}\nDatenfenster: {data_window}\n"
                f"Produktlink: {product_link}\n"
            )
            if existing is None:
                existing = InventoryAlertTask(
                    id=uuid.uuid4(), alert_id=alert_id, recipient=self.RECIPIENT,
                    subject=subject, body=body, status="pending",
                )
                session.add(existing)
            else:
                existing.subject = subject
                existing.body = body
                existing.status = "pending"
                existing.error = ""
            session.flush()
            task_id = existing.id
        try:
            mail_delivery.send_mail(
                to_email=self.RECIPIENT,
                subject=subject,
                text_body=body,
                html_body=mail_delivery.plain_text_to_html(body),
            )
        except Exception as exc:  # noqa: BLE001
            with session_scope(self._session_factory) as session:
                task = session.get(InventoryAlertTask, task_id)
                if task is not None:
                    task.status = "failed"
                    task.error = str(exc)[:2000]
            return InventoryAlertTaskResult(alert_id, task_id, "failed", self.RECIPIENT, subject, body, str(exc))
        with session_scope(self._session_factory) as session:
            task = session.get(InventoryAlertTask, task_id)
            if task is not None:
                task.status = "sent"
                task.sent_at = datetime.datetime.now(datetime.timezone.utc)
        return InventoryAlertTaskResult(alert_id, task_id, "sent", self.RECIPIENT, subject, body)

    @staticmethod
    def _result(task: InventoryAlertTask) -> InventoryAlertTaskResult:
        return InventoryAlertTaskResult(
            alert_id=task.alert_id, task_id=task.id, status=task.status,
            recipient=task.recipient, subject=task.subject, body=task.body, error=task.error,
        )


__all__ = ["InventoryAlertTaskResult", "InventoryAlertTaskService"]
