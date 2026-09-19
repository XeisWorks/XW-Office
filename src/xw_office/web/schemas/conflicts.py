"""HTTP contracts for the Product Hub conflict wizard."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConflictObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source: str
    raw_value: Any = None
    normalized_value: Any = None
    source_revision: str | None = None
    observed_at: datetime.datetime


class ConflictFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    field_path: str
    selected_value: Any = None
    selected_source: str | None = None
    resolution_type: str | None = None
    status: str
    observations: list[ConflictObservationOut] = Field(default_factory=list)


class ConflictActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    channel: str
    action_type: str
    field_path: str | None = None
    before_value: Any = None
    after_value: Any = None
    selected: bool
    status: str
    outbox_event_id: uuid.UUID | None = None
    error: str | None = None
    verified_at: datetime.datetime | None = None


class ConflictCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    conflict_type: str
    severity: str
    status: str
    priority_score: int
    title: str
    summary: str | None = None
    detected_at: datetime.datetime
    last_seen_at: datetime.datetime
    snoozed_until: datetime.datetime | None = None
    resolution_type: str | None = None
    resolution_note: str | None = None
    row_version: int


class ConflictCaseDetailOut(ConflictCaseOut):
    product_sku: str
    product_name: str
    fields: list[ConflictFieldOut]
    actions: list[ConflictActionOut]


class ConflictAdviceOut(BaseModel):
    title: str
    explanation: str
    likely_causes: list[str]
    recommendation: str
    next_steps: list[str]
    confidence: str
    warnings: list[str]
    evidence: list[str]


class ConflictPageOut(BaseModel):
    items: list[ConflictCaseOut]
    total: int
    limit: int
    offset: int


class ConflictSummaryOut(BaseModel):
    open: int
    critical: int
    waiting: int
    partially_resolved: int
    resolved: int


class ConflictScanOut(BaseModel):
    id: uuid.UUID
    differences_found: int
    cases_created: int
    cases_updated: int
    cases_obsoleted: int


class WixSourceSnapshotOut(BaseModel):
    mappings_seen: int
    catalog_products_indexed: int
    products_fetched: int
    products_cached: int
    products_missing_from_index: int
    full_refresh: bool
    payloads_archived: int
    payloads_unchanged: int
    images_created: int
    images_updated: int
    images_marked_stale: int
    conflicts_created: int
    conflicts_updated: int
    conflicts_resolved: int
    mapping_conflicts_created: int
    mapping_conflicts_updated: int
    mapping_conflicts_resolved: int
    errors: list[str] = Field(default_factory=list)


class WixSnapshotScanOut(ConflictScanOut):
    source: WixSourceSnapshotOut


class VersionedRequest(BaseModel):
    expected_row_version: int = Field(ge=1)


class ConflictDecisionRequest(VersionedRequest):
    resolution_type: str
    selected_source: str | None = None
    custom_value: Any = None
    note: str | None = None


class ConflictPreviewRequest(BaseModel):
    channels: list[str] | None = None


class ConflictSnoozeRequest(VersionedRequest):
    until: datetime.datetime
    note: str | None = None
