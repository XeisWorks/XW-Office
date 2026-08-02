"""Dry-run request execution for Outlook add-in integration."""
from __future__ import annotations

import json
import logging
from uuid import uuid4

from pydantic import ValidationError

from xw_office.services.xw_copilot.contracts import (
    XWCopilotError,
    XWCopilotRequest,
    XWCopilotResponse,
)
from xw_office.services.xw_copilot.live_dispatch import XWCopilotLiveDispatcher
from xw_office.services.xw_copilot.service import AuditEntry, XWCopilotService

logger = logging.getLogger(__name__)


class XWCopilotDryRunService:
    """Validate and simulate incoming Outlook add-in requests."""

    def __init__(
        self,
        config_service: XWCopilotService,
        audit_service: XWCopilotService | None = None,
        live_dispatcher: XWCopilotLiveDispatcher | None = None,
    ) -> None:
        self._config_service = config_service
        self._audit_service = audit_service
        self._live = live_dispatcher

    def simulate_raw_request(self, raw_json: str) -> XWCopilotResponse:
        """Parse and validate JSON, then execute a no-side-effect preview."""
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            return XWCopilotResponse(
                accepted=False,
                mode="dry_run",
                action="invalid_json",
                correlation_id=self._new_correlation_id(),
                errors=[
                    XWCopilotError(
                        code="invalid_json",
                        message=str(exc),
                        hint="Send valid JSON payload.",
                    )
                ],
            )

        if not isinstance(data, dict):
            return XWCopilotResponse(
                accepted=False,
                mode="dry_run",
                action="invalid_request",
                correlation_id=self._new_correlation_id(),
                errors=[
                    XWCopilotError(
                        code="invalid_request",
                        message="Top-level JSON object required.",
                        hint="Expected object with tenant, mailbox, action and payload_version.",
                    )
                ],
            )

        try:
            request = XWCopilotRequest.model_validate(data)
        except ValidationError as exc:
            return XWCopilotResponse(
                accepted=False,
                mode="dry_run",
                action=str(data.get("action") or "validation_error"),
                correlation_id=str(data.get("correlation_id") or self._new_correlation_id()),
                errors=[
                    XWCopilotError(
                        code="validation_error",
                        message="Request validation failed.",
                        hint=exc.json(),
                    )
                ],
            )

        return self.simulate(request)

    def simulate(self, request: XWCopilotRequest) -> XWCopilotResponse:
        """Simulate business action execution based on the request action key."""
        correlation_id = request.correlation_id or self._new_correlation_id()
        mode = self._resolved_mode()
        action = request.action.strip().lower()
        preview = self._build_preview(action, request.payload)

        if preview is None:
            response = XWCopilotResponse(
                accepted=False,
                mode=mode,
                action=action,
                correlation_id=correlation_id,
                errors=[
                    XWCopilotError(
                        code="unsupported_action",
                        message=f"Action '{request.action}' is not supported yet.",
                        hint="Use crm.lookup_contact, invoice.read_status or inventory.start_preflight.",
                    )
                ],
            )
        else:
            response = XWCopilotResponse(
                accepted=True,
                mode=mode,
                action=action,
                correlation_id=correlation_id,
                preview=preview,
            )

        self._write_audit(response)
        return response

    def _write_audit(self, response: XWCopilotResponse) -> None:
        if self._audit_service is None:
            return
        try:
            entry = AuditEntry(
                timestamp=XWCopilotService.utc_now(),
                action=response.action,
                correlation_id=response.correlation_id,
                accepted=response.accepted,
                mode=response.mode,
            )
            self._audit_service.append_audit_entry(entry)
        except Exception as exc:
            logger.warning("Failed to write audit entry: %s", exc)

    def _build_preview(self, action: str, payload: dict[str, object]) -> dict[str, object] | None:
        # In live mode, try real dispatch first before falling back to preview.
        if self._resolved_mode() == "live" and self._live is not None:
            try:
                result = self._live.dispatch(action, payload)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning("Live dispatch error for %s: %s", action, exc)

        if action == "crm.lookup_contact":
            query = str(payload.get("query") or "")
            return {
                "service": "crm",
                "operation": "lookup_contact",
                "query": query,
                "dry_run_note": "Would query CRM contacts and return matching records.",
            }
        if action == "invoice.read_status":
            invoice_number = str(payload.get("invoice_number") or "")
            return {
                "service": "invoices",
                "operation": "read_status",
                "invoice_number": invoice_number,
                "dry_run_note": "Would read invoice status and payment state.",
            }
        if action == "inventory.start_preflight":
            sku = str(payload.get("sku") or "")
            quantity = int(payload.get("quantity") or 0)
            return {
                "service": "inventory",
                "operation": "start_preflight",
                "sku": sku,
                "quantity": quantity,
                "dry_run_note": "Would evaluate stock and decide print/no-print (+3 buffer policy).",
            }
        return None

    def _resolved_mode(self) -> str:
        cfg = self._config_service.load_config()
        if cfg.mode == "live":
            logger.info("Dry-run simulator executed while config mode is live.")
        return cfg.mode or "dry_run"

    @staticmethod
    def _new_correlation_id() -> str:
        return str(uuid4())
