"""Typed request/response contract for Outlook add-in integration."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class XWCopilotRequest(BaseModel):
    """Inbound request schema sent by Outlook add-in."""

    model_config = ConfigDict(extra="ignore")

    tenant: str = Field(min_length=1)
    mailbox: str = Field(min_length=1)
    action: str = Field(min_length=1)
    payload_version: str = Field(default="1.0", min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


class XWCopilotError(BaseModel):
    """Structured error for invalid or unsupported requests."""

    code: str
    message: str
    hint: str = ""


class XWCopilotResponse(BaseModel):
    """Outbound response schema used for dry-run and future live mode."""

    accepted: bool
    mode: str
    action: str
    correlation_id: str
    preview: dict[str, Any] = Field(default_factory=dict)
    errors: list[XWCopilotError] = Field(default_factory=list)
