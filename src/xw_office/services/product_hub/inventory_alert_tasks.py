"""Manual, deduplicated Graph task creation for open inventory alerts."""
from __future__ import annotations

from dataclasses import dataclass
import datetime
import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.inventory_alert_task import InventoryAlertTask
from xw_office.models.product_hub import Product, ProductVariant
from xw_office.models.product_hub_inventory import InventoryAlert, InventoryLocation, InventoryStock
from xw_office.services.mailing.service import MailDeliveryService


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

    def list_tasks(self, *, status: str | None = None, limit: int = 100) -> list[InventoryAlertTask]:
        """Return recent durable task attempts for an operational retry view."""
        with session_scope(self._session_factory) as session:
            stmt = select(InventoryAlertTask).order_by(desc(InventoryAlertTask.created_at)).limit(max(1, min(500, int(limit))))
            if status:
                stmt = stmt.where(InventoryAlertTask.status == str(status).strip())
            return list(session.scalars(stmt).all())

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_and_send(
        self,
        alert_id: uuid.UUID,
        *,
        mail_delivery: MailDeliveryService,
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
            if existing is not None:
                # The row lock protects the durable claim, not the Graph call
                # after commit. Never let another caller reuse an active claim.
                if existing.status == "pending":
                    return self._result(existing)
                if existing.status in {"sent", "unknown", "failed"} and not explicit_resend:
                    return self._result(existing)
            variant = session.get(ProductVariant, alert.variant_id)
            product = session.get(Product, variant.product_id) if variant is not None else None
            location = session.get(InventoryLocation, alert.location_id)
            stock = session.get(InventoryStock, (alert.variant_id, alert.location_id))
            sku = str(variant.sku if variant is not None else "unbekannt")
            title = str((variant.name if variant is not None else "") or (product.name if product is not None else sku))
            on_hand = int(stock.on_hand if stock is not None else alert.observed_stock or 0)
            threshold = int(alert.threshold if alert.threshold is not None else 0)
            mode = str(stock.reorder_mode if stock is not None else "auto")
            target_stock = (
                int(stock.target_stock)
                if stock is not None and int(stock.target_stock or 0) > 0
                else threshold
            )
            suggested_order_quantity = max(0, target_stock - on_hand)
            if sales_average_monthly is None and stock is not None:
                full_months = max(0, int(stock.forecast_full_sellable_months or 0))
                sales_average_monthly = (
                    max(0, int(stock.forecast_net_sold_units or 0)) / full_months
                    if full_months
                    else max(0, int(stock.automatic_reorder_point or 0)) / 3
                )
            if three_month_demand is None and stock is not None:
                three_month_demand = int(stock.automatic_reorder_point or 0)
            if data_window == "bis zu 60 vollständige Monate" and stock is not None:
                if stock.forecast_window_start and stock.forecast_window_end:
                    data_window = f"{stock.forecast_window_start} bis {stock.forecast_window_end} ({stock.forecast_data_quality})"
            average_text = "unbekannt" if sales_average_monthly is None else f"{sales_average_monthly:.2f} Stk/Monat"
            demand_text = "unbekannt" if three_month_demand is None else f"{three_month_demand} Stk"
            subject = f"Lageralarm: {sku} – {title}"
            product_link = f"/app/products/{product.id}" if product is not None else "nicht verfügbar"
            body = (
                "Lageralarm aus XW-Office\n\n"
                f"Alarm-ID: {alert.id}\nSKU: {sku}\nProdukttitel: {title}\n"
                f"Lagerort: {location.code if location is not None else 'unbekannt'}\n"
                f"Ist-Bestand: {on_hand}\nAlarmbestand: {threshold}\n"
                f"Alarmmodus: {mode}\nZielbestand: {target_stock}\n"
                f"Empfohlene Bestell-/Nachdruckmenge: {suggested_order_quantity}\n"
                f"Durchschnittlicher Monatsverkauf: {average_text}\n"
                f"Drei-Monats-Bedarf: {demand_text}\nDatenfenster: {data_window}\n"
                f"Erstellt am: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
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
                    # A transport exception cannot prove that Graph rejected
                    # the message. Preserve uncertainty instead of blind retry.
                    task.status = "unknown"
                    task.error = str(exc)[:2000]
            return InventoryAlertTaskResult(alert_id, task_id, "unknown", self.RECIPIENT, subject, body, str(exc))
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
