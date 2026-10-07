"""Credential-isolated persistence for incremental Mollie payment reads."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, Protocol, cast


class SettingsRepository(Protocol):
    def get_value_json(self, key: str) -> str | None: ...

    def mutate_value_json(
        self,
        key: str,
        mutator: Callable[[str | None], str],
    ) -> str: ...


class MolliePaymentCache:
    """Persist the minimum Mollie payment data needed by clearing."""

    def __init__(self, repository: SettingsRepository, access_token: str) -> None:
        digest = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
        self._repository = repository
        self.key = f"clearing.mollie.payment_cache.v1.{digest}"

    def read(self) -> dict[str, Any] | None:
        raw = self._repository.get_value_json(self.key)
        return self._decode(raw)

    def merge(
        self,
        payments: dict[str, dict[str, Any]],
        *,
        full_refresh_at: float | None = None,
    ) -> dict[str, Any]:
        merged_result: dict[str, Any] = {}

        def mutate(raw: str | None) -> str:
            current = self._decode(raw) or {"version": 1, "full_refresh_at": 0.0, "payments": {}}
            current_payments = cast(dict[str, dict[str, Any]], current["payments"])
            for payment_id, candidate in payments.items():
                existing = current_payments.get(payment_id)
                if existing is None or float(candidate.get("fetched_at", 0)) > float(
                    existing.get("fetched_at", 0)
                ):
                    current_payments[payment_id] = candidate
            if full_refresh_at is not None:
                current["full_refresh_at"] = max(
                    float(current.get("full_refresh_at", 0)), full_refresh_at
                )
            merged_result.update(current)
            return json.dumps(current, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

        self._repository.mutate_value_json(self.key, mutate)
        return merged_result

    @staticmethod
    def _decode(raw: str | None) -> dict[str, Any] | None:
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Mollie-Zahlungscache enthaelt ungueltiges JSON.") from exc
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or not isinstance(value.get("payments"), dict)
        ):
            raise ValueError("Mollie-Zahlungscache hat ein ungueltiges Format.")
        payments = value["payments"]
        if any(not isinstance(key, str) or not isinstance(item, dict) for key, item in payments.items()):
            raise ValueError("Mollie-Zahlungscache enthaelt ungueltige Payment-Eintraege.")
        value["full_refresh_at"] = float(value.get("full_refresh_at", 0))
        return value
