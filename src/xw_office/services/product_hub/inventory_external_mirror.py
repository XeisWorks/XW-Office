"""Transactional mirror from external sevDesk feed into Legacy stock settings."""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.inventory_external_mirror import InventoryExternalMirror
from xw_office.models.settings_kv import SettingKV

_STOCK_KEY = "inventory.stock_levels"
_PRODUCTS_KEY = "inventory.products"


@dataclass(frozen=True)
class ExternalMirrorResult:
    status: str
    sku: str
    previous_stock: int | None = None
    new_stock: int | None = None
    detail: str = ""


class InventoryExternalMirrorService:
    """Apply one external invoice/credit delta exactly once to Legacy settings.

    The marker and both legacy JSON snapshots are updated in one database
    transaction. Missing or malformed source values are left untouched and
    returned as ``needs_review`` so a later inventory baseline can recover them.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def apply(
        self,
        *,
        sku: str,
        delta: int,
        idempotency_key: str,
        external_reference: str = "",
    ) -> ExternalMirrorResult:
        clean_sku = str(sku or "").strip().upper()
        key = str(idempotency_key or "").strip()
        if not clean_sku or not key:
            return ExternalMirrorResult("needs_review", clean_sku, detail="SKU und Idempotenzschlüssel sind erforderlich")
        with session_scope(self._session_factory) as session:
            existing = session.scalar(
                select(InventoryExternalMirror).where(InventoryExternalMirror.idempotency_key == key)
            )
            if existing is not None:
                return ExternalMirrorResult(
                    "already_applied", existing.sku, existing.previous_stock, existing.new_stock, existing.status
                )
            stock_row = session.get(SettingKV, _STOCK_KEY, with_for_update=True)
            values = _parse_object(stock_row.value_json if stock_row is not None else None)
            raw_current = values.get(clean_sku)
            if not isinstance(raw_current, (int, float, str)):
                return ExternalMirrorResult("needs_review", clean_sku, detail="Legacy-Bestand für SKU fehlt oder ist ungültig")
            try:
                current = int(raw_current)
            except (TypeError, ValueError):
                return ExternalMirrorResult("needs_review", clean_sku, detail="Legacy-Bestand für SKU fehlt oder ist ungültig")
            if current < 0:
                return ExternalMirrorResult("needs_review", clean_sku, current, current, "Legacy-Bestand ist negativ")
            requested_target = current + int(delta)
            target = max(0, requested_target)
            status = "mirrored" if requested_target >= 0 else "shortage"
            values[clean_sku] = target
            payload = json.dumps(values, ensure_ascii=False)
            if stock_row is None:
                stock_row = SettingKV(key=_STOCK_KEY, value_json=payload)
                session.add(stock_row)
            else:
                stock_row.value_json = payload
            self._update_product_snapshot(session, clean_sku, target)
            session.add(
                InventoryExternalMirror(
                    idempotency_key=key,
                    sku=clean_sku,
                    delta=int(delta),
                    previous_stock=current,
                    new_stock=target,
                    status=status,
                    external_reference=str(external_reference or "")[:240],
                )
            )
            return ExternalMirrorResult(
                status,
                clean_sku,
                current,
                target,
                "Legacy-Bestand war unter der angeforderten Abgangsmenge" if status == "shortage" else "",
            )

    @staticmethod
    def _update_product_snapshot(session: Session, sku: str, target: int) -> None:
        row = session.get(SettingKV, _PRODUCTS_KEY, with_for_update=True)
        products = _parse_list(row.value_json if row is not None else None)
        changed = False
        for product in products:
            if str(product.get("sku") or "").strip().upper() != sku:
                continue
            product["on_hand"] = target
            changed = True
        if not changed:
            return
        payload = json.dumps(products, ensure_ascii=False)
        if row is None:
            session.add(SettingKV(key=_PRODUCTS_KEY, value_json=payload))
        else:
            row.value_json = payload


def _parse_object(raw: str | None) -> dict[str, object]:
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _parse_list(raw: str | None) -> list[dict[str, object]]:
    try:
        value = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


__all__ = ["ExternalMirrorResult", "InventoryExternalMirrorService"]
