"""CRM DTOs."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ContactRecord(BaseModel):
    """Minimal contact row for deduplication."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    email: str | None = None
    phone: str | None = None
    city: str | None = None


class MatchReason(str, Enum):
    """Why two contacts were flagged as possible duplicates.

    Named, reported cascade instead of an opaque score — legacy's match
    cascade always carried an explicit reason (e.g. "wixCustomerId-unique")
    so a user reviewing the queue could trust *why* a pair matched, not
    just that it scored high enough.
    """

    EMAIL_EXACT = "email-exact"
    FUZZY_NAME = "fuzzy-name-score"


class DuplicateCandidate(BaseModel):
    """Pair of contacts that may be duplicates."""

    model_config = ConfigDict(extra="ignore")

    a: ContactRecord
    b: ContactRecord
    score: int = Field(ge=0, le=100, description="Match score 0-100")
    reason: MatchReason = MatchReason.FUZZY_NAME
