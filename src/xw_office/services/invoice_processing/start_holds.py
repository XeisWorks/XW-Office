"""Persistent, per-invoice eligibility for the automatic START flow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


START_HOLDS_KEY = "rechnungen.start_holds.v1"
START_HOLD_REASONS = {
    "customer_question": "Kundenklärung",
    "product_unavailable": "Produkt nicht verfügbar",
    "other": "Sonstiger Grund",
}


@dataclass(frozen=True)
class StartHold:
    invoice_id: str
    reason: str
    note: str = ""
    review_on: str = ""
    updated_at: str = ""

    @property
    def reason_label(self) -> str:
        return START_HOLD_REASONS.get(self.reason, START_HOLD_REASONS["other"])

    @property
    def review_due(self) -> bool:
        if not self.review_on:
            return False
        try:
            return date.fromisoformat(self.review_on) <= date.today()
        except ValueError:
            return False

    def as_payload(self) -> dict[str, str]:
        return {
            "reason": self.reason,
            "note": self.note,
            "review_on": self.review_on,
            "updated_at": self.updated_at,
        }

    @classmethod
    def create(cls, invoice_id: str, reason: str, *, note: str = "", review_on: str = "") -> "StartHold":
        clean_id = str(invoice_id or "").strip()
        if not clean_id:
            raise ValueError("Rechnungs-ID fehlt")
        if reason not in START_HOLD_REASONS:
            raise ValueError("Unbekannter Zurückstellungsgrund")
        return cls(
            invoice_id=clean_id,
            reason=reason,
            note=str(note or "").strip()[:1000],
            review_on=str(review_on or "").strip(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    def from_payload(cls, invoice_id: str, payload: object) -> "StartHold | None":
        if not isinstance(payload, dict):
            return None
        reason = str(payload.get("reason") or "").strip()
        if reason not in START_HOLD_REASONS:
            return None
        return cls(
            invoice_id=invoice_id,
            reason=reason,
            note=str(payload.get("note") or "").strip(),
            review_on=str(payload.get("review_on") or "").strip(),
            updated_at=str(payload.get("updated_at") or "").strip(),
        )
