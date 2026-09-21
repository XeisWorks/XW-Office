"""Pydantic schemas for the Inventory V2 shadow-mode API (PR13/PR14)."""
from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class MovementCreateRequest(BaseModel):
    variant_id: uuid.UUID
    delta: int
    reason: str  # import_baseline | sale | print_run | return | damage | manual_adjustment | recount
    source: str
    idempotency_key: str
    location_code: str = "MAIN"
    external_reference: str = ""
    note: str = ""


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    variant_id: uuid.UUID
    location_id: uuid.UUID
    delta: int
    reason: str
    source: str
    external_reference: str | None = None
    idempotency_key: str
    note: str | None = None
    on_hand_after: int
    actor: str | None = None
    occurred_at: datetime.datetime


class MovementResultOut(BaseModel):
    movement: MovementOut
    alert_opened: uuid.UUID | None = None


class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: uuid.UUID
    location_id: uuid.UUID
    on_hand: int
    reserved: int
    reorder_point: int
    target_stock: int
    default_reprint_qty: int
    version: int
    updated_at: datetime.datetime


class ThresholdUpdateRequest(BaseModel):
    location_code: str = "MAIN"
    reorder_point: int | None = None
    target_stock: int | None = None
    default_reprint_qty: int | None = None


class InventoryAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    variant_id: uuid.UUID
    location_id: uuid.UUID
    type: str
    status: str
    threshold: int | None = None
    observed_stock: int | None = None
    first_triggered_at: datetime.datetime
    last_triggered_at: datetime.datetime
    resolved_at: datetime.datetime | None = None


class ReconcileRequest(BaseModel):
    variant_id: uuid.UUID
    sevdesk_on_hand: int
    location_code: str = "MAIN"


class ReconcileResponse(BaseModel):
    drift_detected: bool


class InventorySummaryOut(BaseModel):
    physical_products: int
    low_stock: int
    out_of_stock: int
    open_reprint_alerts: int
    sync_errors: int
    updated_at: datetime.datetime


class InventoryCutoverCheckOut(BaseModel):
    code: str
    label: str
    state: str
    detail: str


class InventoryCutoverReadinessOut(BaseModel):
    master_enabled: bool
    shadow_enabled: bool
    eligible: bool
    checks: list[InventoryCutoverCheckOut]
    assessed_at: datetime.datetime


class LegacyInventoryShadowConflictOut(BaseModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    product_id: uuid.UUID | None = None
    sku: str
    product_name: str
    variant_name: str = ""
    status: str
    detail: str
    detected_at: datetime.datetime


class LegacyInventoryBaselineItemOut(BaseModel):
    sku: str
    legacy_on_hand: int | None = None
    variant_id: uuid.UUID | None = None
    product_name: str = ""
    status: str
    detail: str


class LegacyInventoryBaselinePreviewOut(BaseModel):
    source_present: bool
    source_hash: str
    shadow_enabled: bool
    items: list[LegacyInventoryBaselineItemOut]
    assessed_at: datetime.datetime


class LegacyInventoryBaselineApplyRequest(BaseModel):
    expected_source_hash: str


class LegacyInventoryBaselineApplyOut(BaseModel):
    applied_skus: list[str]
    blocked_items: list[LegacyInventoryBaselineItemOut]
