"""Small, authenticated web facade for the existing desktop clearing service."""
from __future__ import annotations

import calendar
import json
import logging
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from threading import Lock
from typing import Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.clearing.service import PaymentClearingService

logger = logging.getLogger(__name__)
_VIENNA = ZoneInfo("Europe/Vienna")
_RUN_PREFIX = "clearing.flow.run."
_ACTIVE_KEY = "clearing.flow.active"


class ClearingRunRequest(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class ClearingRunCoordinator:
    """Persist compact job status in the shared Office DB, even across HTTP workers."""

    def __init__(
        self,
        repo: SettingKvRepository,
        service_factory: Callable[[], PaymentClearingService],
        *,
        today: Callable[[], date] = lambda: datetime.now(_VIENNA).date(),
    ) -> None:
        self._repo = repo
        self._service_factory = service_factory
        self._today = today
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flow-clearing")
        self._lock = Lock()

    @staticmethod
    def _key(run_id: str) -> str:
        return _RUN_PREFIX + run_id

    def get(self, run_id: str) -> dict[str, object] | None:
        raw = self._repo.get_value_json(self._key(run_id))
        return json.loads(raw) if raw else None

    def start(self, month: str, idempotency_key: str) -> dict[str, object]:
        if not idempotency_key or len(idempotency_key) > 200:
            raise HTTPException(422, "Idempotency-Key fehlt oder ist zu lang.")
        month_start = date.fromisoformat(month + "-01")
        today = self._today()
        if month_start.year != today.year or month_start.month != today.month:
            raise HTTPException(422, "Flow-Clearing ist nur fuer den laufenden Monat verfuegbar.")
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "xw-flow-clearing:" + idempotency_key))
        with self._lock:
            existing = self.get(run_id)
            if existing is not None:
                if existing.get("month") != month:
                    raise HTTPException(409, "Idempotency-Key wurde fuer einen anderen Monat verwendet.")
                return existing
            initial: dict[str, object] = {
                "run_id": run_id, "month": month, "state": "running", "phase": "analysis",
                "percent": 0, "message": "Analyse startet", "booked": 0, "failed": 0,
                "manual": 0, "already_booked": 0, "warnings": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            def claim_active(raw: str | None) -> str:
                active = json.loads(raw) if raw else None
                if active and active.get("state") == "running" and active.get("run_id") != run_id:
                    raise HTTPException(409, "Ein Clearing-Lauf ist bereits aktiv.")
                return json.dumps({"run_id": run_id, "state": "running"})

            def create_run(raw: str | None) -> str:
                if raw:
                    raise HTTPException(409, "Clearing-Lauf wurde gleichzeitig angelegt; Status erneut laden.")
                return json.dumps(initial)

            self._repo.mutate_values_json({_ACTIVE_KEY: claim_active, self._key(run_id): create_run})
            self._executor.submit(self._execute, run_id, month_start, min(
                today, date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
            ))
            return initial

    def _update(self, run_id: str, **changes: object) -> None:
        def mutate(raw: str | None) -> str:
            if not raw:
                raise RuntimeError("Clearing-Status fehlt")
            state = json.loads(raw)
            state.update(changes)
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            return json.dumps(state)

        self._repo.mutate_value_json(self._key(run_id), mutate)

    def _execute(self, run_id: str, start: date, end: date) -> None:
        try:
            service = self._service_factory()
            analysis = service.analyze(
                start, end,
                progress=lambda value, message: self._update(
                    run_id, percent=min(65, int(value * 0.65)), phase="analysis", message=message,
                ),
            )
            if analysis.warnings:
                # A missing provider must never turn a partial Mollie run into a success.
                self._update(
                    run_id, state="error", percent=65, warnings=len(analysis.warnings),
                    message="Analyse unvollstaendig; keine Buchung ausgefuehrt. Quellen in Office pruefen.",
                )
                return
            selected = [row for row in analysis.candidates if row.selected and row.is_bookable]
            manual = sum(not row.is_bookable and row.status.value != "already_booked" for row in analysis.candidates)
            already = sum(row.status.value == "already_booked" for row in analysis.candidates)
            self._update(
                run_id, phase="booking", percent=65, manual=manual, already_booked=already,
                message=f"{len(selected)} automatisch ausgewaehlte Vorgaenge buchen",
            )
            if not selected:
                self._update(run_id, state="complete", percent=100, message="Keine neuen automatisch buchbaren Vorgaenge.")
                return
            result = service.book_selected(
                selected,
                progress=lambda value, _message: self._update(
                    run_id, percent=65 + min(35, int(value * 0.35)), message="Buchung laeuft",
                ),
            )
            state = "complete" if result.failure_count == 0 and not result.cancelled and not result.warnings else "error"
            self._update(
                run_id, state=state, percent=100, booked=result.success_count,
                failed=result.failure_count, warnings=len(result.warnings),
                message=("Clearing abgeschlossen." if state == "complete" else
                         "Clearing teilweise ausgefuehrt; Details in Office pruefen."),
            )
        except Exception:
            logger.exception("Flow clearing run failed: %s", run_id)
            try:
                self._update(run_id, state="error", message="Clearing fehlgeschlagen; Buchungsstatus in Office pruefen.")
            except Exception:
                logger.exception("Flow clearing status update failed: %s", run_id)
        finally:
            try:
                self._repo.mutate_value_json(
                    _ACTIVE_KEY,
                    lambda raw: json.dumps({"run_id": run_id, "state": "done"})
                    if raw and json.loads(raw).get("run_id") == run_id else (raw or "{}"),
                )
            except Exception:
                logger.exception("Flow clearing active marker release failed: %s", run_id)


def build_clearing_router(
    coordinator: ClearingRunCoordinator | None,
    *,
    secret: str,
    read_enabled: bool,
    write_enabled: bool,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/clearing/runs", tags=["clearing"])

    def require_access(value: str | None) -> None:
        if coordinator is None or not read_enabled or not secret:
            raise HTTPException(503, "Clearing-Dienst ist nicht konfiguriert.")
        if not value or not secrets.compare_digest(value, secret):
            raise HTTPException(401, "Clearing-Zugriff verweigert.")

    @router.post("", status_code=202)
    def start_run(
        body: ClearingRunRequest,
        x_xw_flow_secret: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_access(x_xw_flow_secret)
        if not write_enabled:
            raise HTTPException(503, "Clearing-Buchung ist nicht aktiviert.")
        assert coordinator is not None
        return coordinator.start(body.month, idempotency_key or "")

    @router.get("/{run_id}")
    def get_run(run_id: uuid.UUID, x_xw_flow_secret: str | None = Header(default=None)) -> dict[str, object]:
        require_access(x_xw_flow_secret)
        assert coordinator is not None
        result = coordinator.get(str(run_id))
        if result is None:
            raise HTTPException(404, "Clearing-Lauf nicht gefunden.")
        return result

    return router
