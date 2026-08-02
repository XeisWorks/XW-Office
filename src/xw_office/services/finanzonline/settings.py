"""FinanzOnline / ELSTER-related settings (identifiers only in scaffold)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FinanzOnlineSettings(BaseModel):
    """Placeholder for participant IDs once loaded from env/DB."""

    model_config = ConfigDict(extra="ignore")

    participant_id: str | None = None
    user_id: str | None = None
