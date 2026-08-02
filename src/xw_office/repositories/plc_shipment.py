"""Persistence access for PLC submission idempotency and audit states."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime
from decimal import Decimal
import json
from collections.abc import Generator

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.plc_shipment import PlcShipment


@dataclass(frozen=True)
class PlcShipmentReservation:
    state: str
    shipment: PlcShipment


@dataclass(frozen=True)
class PlcPrintedShipment:
    country_iso2: str
    product_code: str
    weight_kg: Decimal | None
    price_eur: Decimal | None
    printed_at: datetime.datetime


class PlcShipmentRepository:
    """Reserve PLC requests before a remote call and retain its safe outcome."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def reserve(
        self,
        *,
        request_key: str,
        invoice_id: str,
        reference: str,
        invoice_number: str,
        mode: str,
        transport: str,
        product_code: str,
        country_iso2: str,
        weight_kg: Decimal | None = None,
        price_eur: Decimal | None = None,
    ) -> PlcShipmentReservation:
        with self._scope() as session:
            bind = session.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:request_key, 0))"),
                    {"request_key": request_key},
                )
            row = session.scalar(select(PlcShipment).where(PlcShipment.request_key == request_key))
            if row is not None:
                if row.status in {"created", "print_queued", "printed"}:
                    return PlcShipmentReservation("already_created", row)
                if row.status in {"sending", "unknown"}:
                    return PlcShipmentReservation("blocked", row)
                row.status = "sending"
                row.error_code = ""
                row.error_message = ""
                row.weight_kg = weight_kg
                row.price_eur = price_eur
                return PlcShipmentReservation("reserved", row)

            row = PlcShipment(
                request_key=request_key,
                invoice_id=invoice_id,
                reference=reference,
                invoice_number=invoice_number,
                mode=mode,
                transport=transport,
                product_code=product_code,
                country_iso2=country_iso2,
                weight_kg=weight_kg,
                price_eur=price_eur,
                status="sending",
            )
            session.add(row)
            session.flush()
            return PlcShipmentReservation("reserved", row)

    def mark_created(
        self,
        request_key: str,
        *,
        tracking_codes: tuple[str, ...],
        label_sha256: str,
    ) -> PlcShipment | None:
        return self._mark(
            request_key,
            status="created",
            tracking_codes_json=json.dumps(list(tracking_codes)),
            label_sha256=label_sha256,
            error_code="",
            error_message="",
        )

    def mark_print_queued(self, request_key: str, print_job_id: str) -> PlcShipment | None:
        return self._mark(request_key, status="print_queued", print_job_id=print_job_id)

    def mark_printed_by_job_id(self, print_job_id: str) -> PlcShipment | None:
        with self._scope() as session:
            row = session.scalar(
                select(PlcShipment).where(PlcShipment.print_job_id == str(print_job_id or ""))
            )
            if row is None:
                return None
            row.status = "printed"
            row.printed_at = func.now()
            session.flush()
            return row

    def list_printed_since(self, since: datetime.datetime) -> list[PlcPrintedShipment]:
        with self._scope() as session:
            rows = session.execute(
                select(
                    PlcShipment.country_iso2,
                    PlcShipment.product_code,
                    PlcShipment.weight_kg,
                    PlcShipment.price_eur,
                    PlcShipment.printed_at,
                )
                .where(PlcShipment.status == "printed")
                .where(PlcShipment.mode == "LIVE")
                .where(PlcShipment.printed_at.is_not(None))
                .where(PlcShipment.printed_at >= since)
                .order_by(PlcShipment.printed_at)
            ).all()
            return [
                PlcPrintedShipment(
                    country_iso2=str(row.country_iso2 or ""),
                    product_code=str(row.product_code or ""),
                    weight_kg=Decimal(row.weight_kg) if row.weight_kg is not None else None,
                    price_eur=Decimal(row.price_eur) if row.price_eur is not None else None,
                    printed_at=row.printed_at,
                )
                for row in rows
                if row.printed_at is not None
            ]

    def mark_failed(self, request_key: str, *, error_code: str, error_message: str) -> PlcShipment | None:
        return self._mark(
            request_key,
            status="failed",
            error_code=str(error_code or "")[:64],
            error_message=str(error_message or "")[:2000],
        )

    def mark_unknown(self, request_key: str, *, error_message: str) -> PlcShipment | None:
        return self._mark(
            request_key,
            status="unknown",
            error_code="TRANSPORT_UNKNOWN",
            error_message=str(error_message or "")[:2000],
        )

    def _mark(self, request_key: str, **values: str) -> PlcShipment | None:
        with self._scope() as session:
            row = session.scalar(select(PlcShipment).where(PlcShipment.request_key == request_key))
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            session.flush()
            return row
