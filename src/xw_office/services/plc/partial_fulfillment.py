"""Persistent, line-level progress for partially dispatched PLC orders."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xw_office.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "plc.partial_fulfillments.v1"


class PartialFulfillmentStore:
    """Track dispatched base quantities per Wix order and product line.

    Railway/PostgreSQL is used when configured so all office PCs see the same
    open quantities. A local state file keeps the workflow usable offline.
    """

    def __init__(self, path: Path, settings_repo: "SettingKvRepository | None" = None) -> None:
        self._path = path
        self._settings_repo = settings_repo
        self._lock = Lock()

    @staticmethod
    def _decode(raw: str | None) -> dict[str, dict[str, int]]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        orders = payload.get("orders", payload)
        if not isinstance(orders, dict):
            return {}
        decoded: dict[str, dict[str, int]] = {}
        for order, items in orders.items():
            if not isinstance(items, dict):
                continue
            quantities: dict[str, int] = {}
            for item_key, quantity in items.items():
                try:
                    quantities[str(item_key)] = max(0, int(quantity))
                except (TypeError, ValueError):
                    continue
            decoded[str(order)] = quantities
        return decoded

    @staticmethod
    def _encode(orders: dict[str, dict[str, int]]) -> str:
        return json.dumps({"orders": orders}, ensure_ascii=False, sort_keys=True)

    def _read_local(self) -> str | None:
        try:
            return self._path.read_text(encoding="utf-8") if self._path.is_file() else None
        except OSError as exc:
            logger.warning("Partial PLC fulfillment state unreadable %s: %s", self._path, exc)
            return None

    def fulfilled_quantities(self, order_reference: str) -> dict[str, int]:
        key = str(order_reference or "").strip()
        if not key:
            return {}
        with self._lock:
            raw = self._settings_repo.get_value_json(_SETTINGS_KEY) if self._settings_repo else self._read_local()
            return dict(self._decode(raw).get(key, {}))

    def add_dispatched_quantities(self, order_reference: str, quantities: dict[str, int]) -> None:
        key = str(order_reference or "").strip()
        additions: dict[str, int] = {}
        for item, quantity in quantities.items():
            try:
                normalized = int(quantity)
            except (TypeError, ValueError):
                continue
            if normalized > 0:
                additions[str(item)] = normalized
        if not key or not additions:
            return

        def update(raw: str | None) -> str:
            orders = self._decode(raw)
            current = orders.setdefault(key, {})
            for item_key, quantity in additions.items():
                current[item_key] = current.get(item_key, 0) + quantity
            return self._encode(orders)

        with self._lock:
            if self._settings_repo is not None:
                self._settings_repo.mutate_value_json(_SETTINGS_KEY, update)
                return
            orders = self._decode(self._read_local())
            current = orders.setdefault(key, {})
            for item_key, quantity in additions.items():
                current[item_key] = current.get(item_key, 0) + quantity
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(self._encode(orders), encoding="utf-8")
            except OSError as exc:
                logger.warning("Partial PLC fulfillment state unwritable %s: %s", self._path, exc)
