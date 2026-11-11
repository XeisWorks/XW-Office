"""Persistent overlap checkpoint for the sevDesk invoice inventory feed."""
from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from typing import Protocol

_CHECKPOINT_KEY = "product_hub.sevdesk_invoice_feed_checkpoint.v1"
_INVENTORY_START_KEY = "product_hub.sevdesk_invoice_feed_start.v1"
_OVERLAP_DAYS = 30


class CheckpointRepository(Protocol):
    def get_value_json(self, key: str) -> str | None: ...
    def mutate_value_json(self, key: str, mutator: Callable[[str | None], str]) -> str: ...


def resolve_invoice_feed_since(
    repository: CheckpointRepository,
    *,
    requested_since: datetime.date | None = None,
    today: datetime.date | None = None,
) -> datetime.date:
    """Use an explicit date or resume from the last successful checkpoint.

    A fixed overlap absorbs delayed provider visibility. A long outage is safe:
    the checkpoint does not advance on an incomplete poll, so the next run scans
    the entire unprocessed interval plus the overlap.
    """
    if requested_since is not None:
        candidate = requested_since
    else:
        current_day = today or datetime.date.today()
        raw = repository.get_value_json(_CHECKPOINT_KEY)
        if not raw:
            candidate = current_day - datetime.timedelta(days=_OVERLAP_DAYS)
        else:
            try:
                payload = json.loads(raw)
                stored = datetime.date.fromisoformat(str(payload["last_successful_date"]))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("sevDesk-Inventar-Wasserstand ist ungueltig; Poll abgebrochen") from exc
            candidate = stored - datetime.timedelta(days=_OVERLAP_DAYS)
    raw_start = repository.get_value_json(_INVENTORY_START_KEY)
    if not raw_start:
        return candidate
    try:
        start_payload = json.loads(raw_start)
        first_eligible = datetime.date.fromisoformat(str(start_payload["first_eligible_date"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("sevDesk-Inventur-Stichtag ist ungueltig; Poll abgebrochen") from exc
    return max(candidate, first_eligible)


def set_invoice_feed_start(
    repository: CheckpointRepository,
    *,
    first_eligible_date: datetime.date,
) -> None:
    """Persist the first date whose finalized invoices may affect the new baseline.

    A confirmed physical count already includes all sales up to its cutover
    moment.  The next eligible date is therefore normally the following day;
    the value is monotonic so a later retry can never reopen historical data.
    """
    if not isinstance(first_eligible_date, datetime.date):
        raise TypeError("first_eligible_date muss ein Datum sein")

    def update(raw: str | None) -> str:
        if raw:
            try:
                previous = datetime.date.fromisoformat(
                    str(json.loads(raw)["first_eligible_date"])
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("sevDesk-Inventur-Stichtag ist ungueltig; Poll abgebrochen") from exc
            first = max(previous, first_eligible_date)
        else:
            first = first_eligible_date
        return json.dumps({"first_eligible_date": first.isoformat()})

    mutate = getattr(repository, "mutate_value_json", None)
    if not callable(mutate):
        raise RuntimeError("Atomarer sevDesk-Inventur-Stichtag fehlt")
    mutate(_INVENTORY_START_KEY, update)


def advance_invoice_feed_checkpoint(
    repository: CheckpointRepository,
    *,
    completed_through: datetime.date | None = None,
) -> None:
    """Advance only after the full invoice poll had no unresolved records."""
    target = completed_through or datetime.date.today()
    mutate = getattr(repository, "mutate_value_json", None)
    if not callable(mutate):
        raise RuntimeError("Atomarer sevDesk-Inventar-Wasserstand fehlt")

    def update(raw: str | None) -> str:
        if raw:
            try:
                previous = datetime.date.fromisoformat(
                    str(json.loads(raw)["last_successful_date"])
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "sevDesk-Inventar-Wasserstand ist ungueltig; Poll abgebrochen"
                ) from exc
            final = max(previous, target)
        else:
            final = target
        return json.dumps({"last_successful_date": final.isoformat()})

    mutate(_CHECKPOINT_KEY, update)


__all__ = [
    "advance_invoice_feed_checkpoint",
    "resolve_invoice_feed_since",
    "set_invoice_feed_start",
]
