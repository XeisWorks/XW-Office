"""Persistence access for PLC submission idempotency and audit states."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime
from decimal import Decimal
import json
import uuid
from collections.abc import Generator

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.plc_shipment import PlcParcelManifest, PlcShipment, PlcTrackingEvent
from xw_office.services.post_tracking import PostTrackingEvent, parse_post_tracking_xml


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
    shipment_count: int = 1


@dataclass(frozen=True)
class PlcParcelEvidence:
    shipment_id: str
    reference: str
    status: str
    created_at: datetime.datetime
    package_number: int
    package_count: int
    weight_kg: Decimal | None
    contents: tuple[dict[str, object], ...]
    tracking_code: str
    available_codes: tuple[str, ...]
    code_assignment: str
    confirmed_at: datetime.datetime | None
    packing_pdf_sha256: str
    events: tuple[PostTrackingEvent, ...] = ()


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
        parcel_snapshots: tuple[dict[str, object], ...] = (),
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
                self._replace_parcel_snapshots(session, row, parcel_snapshots)
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
            self._replace_parcel_snapshots(session, row, parcel_snapshots)
            return PlcShipmentReservation("reserved", row)

    @staticmethod
    def _replace_parcel_snapshots(
        session: Session, shipment: PlcShipment, snapshots: tuple[dict[str, object], ...]
    ) -> None:
        session.execute(delete(PlcParcelManifest).where(PlcParcelManifest.shipment_id == shipment.id))
        session.flush()
        for index, snapshot in enumerate(snapshots, start=1):
            session.add(PlcParcelManifest(
                shipment_id=shipment.id,
                package_number=index,
                parcel_reference=str(snapshot.get("reference") or ""),
                weight_kg=Decimal(str(snapshot["weight_kg"])) if snapshot.get("weight_kg") is not None else None,
                contents_json=json.dumps(snapshot.get("contents") or [], ensure_ascii=False),
            ))

    def mark_created(
        self,
        request_key: str,
        *,
        tracking_codes: tuple[str, ...],
        label_sha256: str,
        collo_codes: tuple[tuple[str, ...], ...] = (),
    ) -> PlcShipment | None:
        with self._scope() as session:
            row = session.scalar(select(PlcShipment).where(PlcShipment.request_key == request_key))
            if row is None:
                return None
            row.status = "created"
            row.tracking_codes_json = json.dumps(list(tracking_codes))
            row.response_collo_codes_json = json.dumps([list(group) for group in collo_codes])
            row.label_sha256 = label_sha256
            row.error_code = ""
            row.error_message = ""
            parcels = session.scalars(
                select(PlcParcelManifest).where(PlcParcelManifest.shipment_id == row.id)
            ).all()
            # Only one physical parcel and one returned code are unambiguous.
            if len(parcels) == 1 and len(tracking_codes) == 1:
                parcels[0].tracking_code = tracking_codes[0]
                parcels[0].code_assignment = "single_parcel"
            session.flush()
            return row

    def list_parcel_evidence(self, *, invoice_id: str, invoice_number: str = "") -> list[PlcParcelEvidence]:
        predicates = [PlcShipment.invoice_id == invoice_id]
        if invoice_number:
            predicates.append(PlcShipment.invoice_number == invoice_number)
        with self._scope() as session:
            shipments = session.scalars(
                select(PlcShipment)
                .where(or_(*predicates))
                .where(PlcShipment.status.in_(("created", "print_queued", "printed")))
                .order_by(PlcShipment.created_at, PlcShipment.id)
            ).all()
            evidence: list[PlcParcelEvidence] = []
            for shipment in shipments:
                parcels = session.scalars(
                    select(PlcParcelManifest)
                    .where(PlcParcelManifest.shipment_id == shipment.id)
                    .order_by(PlcParcelManifest.package_number)
                ).all()
                codes = tuple(str(code) for code in json.loads(shipment.tracking_codes_json or "[]"))
                for parcel in parcels:
                    contents = json.loads(parcel.contents_json or "[]")
                    tracking_events = session.scalars(
                        select(PlcTrackingEvent)
                        .where(PlcTrackingEvent.tracking_code == parcel.tracking_code)
                        .order_by(PlcTrackingEvent.occurred_at, PlcTrackingEvent.event_id)
                    ).all() if parcel.tracking_code else []
                    evidence.append(PlcParcelEvidence(
                        shipment_id=str(shipment.id), reference=shipment.reference,
                        status=shipment.status, created_at=shipment.created_at,
                        package_number=parcel.package_number, package_count=len(parcels),
                        weight_kg=parcel.weight_kg, contents=tuple(contents),
                        tracking_code=parcel.tracking_code, available_codes=codes,
                        code_assignment=parcel.code_assignment, confirmed_at=parcel.confirmed_at,
                        packing_pdf_sha256=parcel.packing_pdf_sha256,
                        events=tuple(PostTrackingEvent(
                            tracking_code=event.tracking_code, event_id=event.event_id,
                            occurred_at=event.occurred_at, event_type=event.event_type,
                            event_reason=event.event_reason,
                            event_postal_code=event.event_postal_code,
                            event_city=event.event_city, event_country=event.event_country,
                            source_sha256=event.source_sha256,
                        ) for event in tracking_events),
                    ))
            return evidence

    def import_post_tracking_xml(
        self, raw: bytes, *, invoice_id: str, invoice_number: str = ""
    ) -> int:
        """Store only events whose code belongs to the selected invoice's PLC response."""
        events = parse_post_tracking_xml(raw)
        predicates = [PlcShipment.invoice_id == invoice_id]
        if invoice_number:
            predicates.append(PlcShipment.invoice_number == invoice_number)
        with self._scope() as session:
            shipments = session.scalars(select(PlcShipment).where(or_(*predicates))).all()
            known_codes = {
                str(code)
                for shipment in shipments
                for code in json.loads(shipment.tracking_codes_json or "[]")
            }
            count = 0
            for event in events:
                if event.tracking_code not in known_codes:
                    continue
                existing = session.scalar(select(PlcTrackingEvent).where(
                    PlcTrackingEvent.tracking_code == event.tracking_code,
                    PlcTrackingEvent.event_id == event.event_id,
                ))
                if existing is not None:
                    continue
                session.add(PlcTrackingEvent(**event.__dict__))
                count += 1
            session.flush()
            return count

    def confirm_parcel_code(self, *, shipment_id: str, package_number: int, tracking_code: str) -> bool:
        code = tracking_code.strip()
        with self._scope() as session:
            try:
                shipment_uuid = uuid.UUID(shipment_id)
            except ValueError:
                return False
            shipment = session.get(PlcShipment, shipment_uuid)
            if shipment is None or shipment.status not in {"created", "print_queued", "printed"}:
                return False
            if code not in json.loads(shipment.tracking_codes_json or "[]"):
                return False
            parcel = session.scalar(select(PlcParcelManifest).where(
                PlcParcelManifest.shipment_id == shipment.id,
                PlcParcelManifest.package_number == package_number,
            ))
            if parcel is None:
                return False
            assigned = session.scalar(select(PlcParcelManifest).where(
                PlcParcelManifest.shipment_id == shipment.id,
                PlcParcelManifest.tracking_code == code,
                PlcParcelManifest.id != parcel.id,
            ))
            if assigned is not None:
                return False
            parcel.tracking_code = code
            parcel.code_assignment = "operator_confirmed"
            parcel.confirmed_at = datetime.datetime.now(datetime.timezone.utc)
            session.flush()
            return True

    def set_packing_pdf_sha256(self, request_key: str, sha256: str) -> None:
        with self._scope() as session:
            shipment = session.scalar(select(PlcShipment).where(PlcShipment.request_key == request_key))
            if shipment is None:
                return
            for parcel in session.scalars(select(PlcParcelManifest).where(
                PlcParcelManifest.shipment_id == shipment.id
            )):
                parcel.packing_pdf_sha256 = sha256

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
