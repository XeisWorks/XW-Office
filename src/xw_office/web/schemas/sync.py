"""Pydantic schemas for the sync/conflict/outbox-worker API (PR11)."""
from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class SyncConflictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: str
    entity_type: str
    internal_entity_id: uuid.UUID
    field_name: str
    hub_value: object | None = None
    external_value: object | None = None
    detected_at: datetime.datetime
    resolved_at: datetime.datetime | None = None
    resolution: str | None = None
    resolved_by: str | None = None


class ConflictResolveRequest(BaseModel):
    resolution: str  # keep_hub_and_push | accept_external | ignore_once


class OutboxWorkerRunOut(BaseModel):
    processed: int
    failed: int
    skipped_no_handler: int
    errors: list[str]


class DeadOutboxEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    aggregate_type: str
    aggregate_id: uuid.UUID
    event_type: str
    attempts: int
    last_error: str | None = None
    created_at: datetime.datetime
