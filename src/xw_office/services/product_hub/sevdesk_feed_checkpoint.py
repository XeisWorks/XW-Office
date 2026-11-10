"""Persistent overlap checkpoint for the sevDesk invoice inventory feed."""
from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from typing import Protocol

_CHECKPOINT_KEY = "product_hub.sevdesk_invoice_feed_checkpoint.v1"
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
        return requested_since
    current_day = today or datetime.date.today()
    raw = repository.get_value_json(_CHECKPOINT_KEY)
    if not raw:
        return current_day - datetime.timedelta(days=_OVERLAP_DAYS)
    try:
        payload = json.loads(raw)
        stored = datetime.date.fromisoformat(str(payload["last_successful_date"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("sevDesk-Inventar-Wasserstand ist ungueltig; Poll abgebrochen") from exc
    return stored - datetime.timedelta(days=_OVERLAP_DAYS)


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


__all__ = ["advance_invoice_feed_checkpoint", "resolve_invoice_feed_since"]
