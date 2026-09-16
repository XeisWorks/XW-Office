"""Sync/conflict/outbox-worker API (PR11).

Auth is applied where this router is *included* (``web/app.py``), matching
``routers/products.py``'s convention. Every route here is gated by the same
``product_hub_edit_enabled`` kill switch as the edit API — resolving a conflict or
running the outbox worker are both write-adjacent actions (a resolution can push to
Wix; running the worker can too, once push is enabled), so they share PR09's "first
write-capable surface" caution rather than getting a third separate flag.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Generator

from fastapi import APIRouter, Depends, HTTPException, Query, status

from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.outbox_worker import OutboxWorker
from xw_office.web.schemas.sync import (
    ConflictResolveRequest,
    DeadOutboxEventOut,
    OutboxWorkerRunOut,
    SyncConflictOut,
)

SyncRepoDependency = Callable[[], Generator[SyncRepository, None, None]]
WorkerDependency = Callable[[], OutboxWorker]
ResolveConflictFn = Callable[[uuid.UUID, str], None]


def build_sync_router(
    get_sync_repo: SyncRepoDependency,
    get_worker: WorkerDependency,
    resolve_conflict: ResolveConflictFn,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sync", tags=["product-hub-sync"])

    @router.get("/conflicts", response_model=list[SyncConflictOut])
    def list_conflicts(
        channel: str | None = Query(default=None),
        repo: SyncRepository = Depends(get_sync_repo),
    ) -> list[SyncConflictOut]:
        return [
            SyncConflictOut.model_validate(c) for c in repo.list_open_sync_conflicts(channel=channel)
        ]

    @router.post("/conflicts/{conflict_id}/resolve", response_model=SyncConflictOut)
    def resolve(
        conflict_id: uuid.UUID,
        body: ConflictResolveRequest,
        repo: SyncRepository = Depends(get_sync_repo),
    ) -> SyncConflictOut:
        try:
            resolve_conflict(conflict_id, body.resolution)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        resolved = repo.get_sync_conflict(conflict_id)
        if resolved is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found")
        return SyncConflictOut.model_validate(resolved)

    @router.post("/worker/run-once", response_model=OutboxWorkerRunOut)
    def run_worker_once(
        limit: int = Query(default=50, ge=1, le=500),
        worker: OutboxWorker = Depends(get_worker),
    ) -> OutboxWorkerRunOut:
        summary = worker.process_once(limit=limit)
        return OutboxWorkerRunOut(
            processed=summary.processed,
            failed=summary.failed,
            skipped_no_handler=summary.skipped_no_handler,
            errors=summary.errors,
        )

    @router.get("/worker/dead-events", response_model=list[DeadOutboxEventOut])
    def dead_events(worker: OutboxWorker = Depends(get_worker)) -> list[DeadOutboxEventOut]:
        return [DeadOutboxEventOut.model_validate(e) for e in worker.list_dead_events()]

    return router
