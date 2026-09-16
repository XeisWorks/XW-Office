"""Pydantic schemas for the dealer sharing API (PR12)."""
from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class ShareCreateRequest(BaseModel):
    title: str
    field_whitelist: list[str] | None = None
    price_list_code: str | None = None
    allow_csv: bool = True
    allow_xlsx: bool = True
    allow_images: bool = True
    expires_at: datetime.datetime | None = None


class ShareOut(BaseModel):
    """Admin-facing listing — never includes the token (it isn't stored)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
    field_whitelist: list[object]
    allow_csv: bool
    allow_xlsx: bool
    allow_images: bool
    expires_at: datetime.datetime | None = None
    revoked_at: datetime.datetime | None = None
    created_at: datetime.datetime
    last_access_at: datetime.datetime | None = None


class ShareCreatedOut(ShareOut):
    """Returned exactly once, at creation — the only response that ever carries the
    plaintext token. It cannot be retrieved again afterwards."""

    token: str
    share_url: str
