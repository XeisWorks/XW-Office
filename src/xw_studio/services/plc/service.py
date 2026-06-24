"""Orchestrate PLC webservice calls with idempotency-safe audit states."""
from __future__ import annotations

import hashlib
import threading

from xw_studio.repositories.plc_shipment import PlcShipmentRepository
from xw_studio.services.plc.models import PlcShipmentDraft
from xw_studio.services.plc.webservice import (
    PlcWebserviceClient,
    PlcWebserviceError,
    PlcWebserviceRejectedError,
    PlcWebserviceResult,
    PlcWebserviceSettings,
    PlcWebserviceTransportError,
)


class PlcDuplicateShipmentError(PlcWebserviceError):
    """The same fully specified shipment was already accepted by PLC."""


class PlcSubmissionBlockedError(PlcWebserviceError):
    """A prior transport result is uncertain, so retrying could duplicate a parcel."""


class PlcShipmentService:
    """Small service boundary between UI, remote SOAP and persistent audit."""

    def __init__(
        self,
        webservice_client: PlcWebserviceClient,
        audit_repository: PlcShipmentRepository | None = None,
    ) -> None:
        self._webservice_client = webservice_client
        self._audit_repository = audit_repository
        self._memory_states: dict[str, str] = {}
        self._memory_lock = threading.Lock()

    def submit_webservice(
        self,
        settings: PlcWebserviceSettings,
        shipment: PlcShipmentDraft,
    ) -> PlcWebserviceResult:
        request_key = shipment.request_fingerprint()
        self._reserve(request_key, shipment)
        try:
            result = self._webservice_client.submit(settings, shipment)
        except PlcWebserviceRejectedError as exc:
            self._mark_failed(request_key, exc.error_code, exc.error_message)
            raise
        except PlcWebserviceTransportError as exc:
            # A timeout can occur after PLC accepted the request. Never resend it blindly.
            self._mark_unknown(request_key, str(exc))
            raise
        except PlcWebserviceError as exc:
            self._mark_failed(request_key, "CLIENT_ERROR", str(exc))
            raise

        label_sha256 = hashlib.sha256(result.pdf_bytes).hexdigest()
        if self._audit_repository is not None:
            self._audit_repository.mark_created(
                request_key,
                tracking_codes=result.tracking_codes,
                label_sha256=label_sha256,
            )
        else:
            with self._memory_lock:
                self._memory_states[request_key] = "created"
        return result

    def mark_print_queued(self, shipment: PlcShipmentDraft, print_job_id: str) -> None:
        request_key = shipment.request_fingerprint()
        if self._audit_repository is not None:
            self._audit_repository.mark_print_queued(request_key, print_job_id)
        else:
            with self._memory_lock:
                self._memory_states[request_key] = "print_queued"

    def _reserve(self, request_key: str, shipment: PlcShipmentDraft) -> None:
        if self._audit_repository is not None:
            reservation = self._audit_repository.reserve(
                request_key=request_key,
                invoice_id=shipment.invoice_id,
                reference=shipment.reference,
                invoice_number=shipment.invoice_number,
                mode=shipment.mode,
                transport="webservice",
                product_code=shipment.product_id,
                country_iso2=shipment.country_iso2,
            )
            if reservation.state == "already_created":
                raise PlcDuplicateShipmentError(
                    "Diese PLC-Sendung wurde bereits erstellt. Bitte nicht erneut Ã¼bermitteln."
                )
            if reservation.state == "blocked":
                raise PlcSubmissionBlockedError(
                    "Der vorherige PLC-Aufruf hat einen unklaren Status. "
                    "Vor einem erneuten Versand bitte PLC/Tracking prÃ¼fen."
                )
            return

        with self._memory_lock:
            state = self._memory_states.get(request_key, "")
            if state in {"created", "print_queued", "printed"}:
                raise PlcDuplicateShipmentError(
                    "Diese PLC-Sendung wurde bereits erstellt. Bitte nicht erneut Ã¼bermitteln."
                )
            if state in {"sending", "unknown"}:
                raise PlcSubmissionBlockedError(
                    "Der vorherige PLC-Aufruf hat einen unklaren Status. "
                    "Vor einem erneuten Versand bitte PLC/Tracking prÃ¼fen."
                )
            self._memory_states[request_key] = "sending"

    def _mark_failed(self, request_key: str, error_code: str, error_message: str) -> None:
        if self._audit_repository is not None:
            self._audit_repository.mark_failed(
                request_key,
                error_code=error_code,
                error_message=error_message,
            )
            return
        with self._memory_lock:
            self._memory_states[request_key] = "failed"

    def _mark_unknown(self, request_key: str, error_message: str) -> None:
        if self._audit_repository is not None:
            self._audit_repository.mark_unknown(request_key, error_message=error_message)
            return
        with self._memory_lock:
            self._memory_states[request_key] = "unknown"
