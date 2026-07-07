"""sevDesk Part API client for product sync comparisons."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from xw_studio.services.http_client import SevdeskConnection

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


class SevdeskPart(BaseModel):
    """Minimal product/article row from sevDesk."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    sku: str = ""
    name: str = ""
    price_eur: str = ""
    stock_qty: int = 0
    # False => digital product (stockEnabled:false in sevDesk) — show ∞ in UI
    stock_enabled: bool = True
    text: str = ""
    tax_rate: float | None = None
    category_id: str = ""
    category_name: str = ""
    unity: dict[str, Any] = {}
    internal_comment: str = ""


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _parse_part(raw: dict[str, Any]) -> SevdeskPart:
    pid = str(raw.get("id") or "")
    sku = str(
        raw.get("partNumber")
        or raw.get("partnumber")
        or raw.get("sku")
        or raw.get("code")
        or ""
    )
    name = str(raw.get("name") or raw.get("text") or "")
    price = str(
        raw.get("price")
        or raw.get("priceNet")
        or raw.get("priceGross")
        or ""
    )
    stock = _to_int(raw.get("stock") or raw.get("quantity") or raw.get("stockAmount") or 0)
    stock_enabled_raw = raw.get("stockEnabled")
    # sevDesk returns "1"/1/True for enabled, "0"/0/False for disabled
    if isinstance(stock_enabled_raw, bool):
        stock_enabled = stock_enabled_raw
    elif isinstance(stock_enabled_raw, (int, float)):
        stock_enabled = bool(int(stock_enabled_raw))
    elif isinstance(stock_enabled_raw, str):
        stock_enabled = stock_enabled_raw.strip() not in ("0", "false", "")
    else:
        stock_enabled = True  # default: assume physical
    category = raw.get("category") if isinstance(raw.get("category"), dict) else {}
    unity = raw.get("unity") if isinstance(raw.get("unity"), dict) else {}
    tax_rate_raw = raw.get("taxRate")
    try:
        tax_rate = float(tax_rate_raw) if tax_rate_raw not in (None, "") else None
    except (TypeError, ValueError):
        tax_rate = None
    return SevdeskPart(
        id=pid, sku=sku, name=name, price_eur=price,
        stock_qty=max(0, stock), stock_enabled=stock_enabled,
        text=str(raw.get("text") or raw.get("description") or ""),
        tax_rate=tax_rate,
        category_id=str(category.get("id") or ""),
        category_name=str(category.get("name") or category.get("displayName") or ""),
        unity=dict(unity) if unity else {},
        internal_comment=str(
            raw.get("internalComment")
            or raw.get("internalNote")
            or raw.get("internal_comment")
            or ""
        ),
    )


class PartClient:
    """Read sevDesk products for cross-system sync checks."""

    def __init__(self, connection: SevdeskConnection) -> None:
        self._conn = connection
        self._parts_cache: list[SevdeskPart] = []
        self._parts_cache_updated_at: datetime | None = None

    @property
    def parts_cache_updated_at(self) -> datetime | None:
        return self._parts_cache_updated_at

    def list_parts(self, *, max_pages: int = 20, refresh_cache: bool = False) -> list[SevdeskPart]:
        """Return sevDesk parts.

        - ``refresh_cache=True`` fetches from API and updates in-memory cache.
        - default returns cache when available.
        - when cache is empty and refresh is False, data is fetched but cache remains untouched.
        """
        if not refresh_cache and self._parts_cache:
            return list(self._parts_cache)
        rows = self._fetch_parts(max_pages=max_pages)
        if refresh_cache:
            self._parts_cache = list(rows)
            self._parts_cache_updated_at = datetime.now(timezone.utc)
        return rows

    def _fetch_parts(self, *, max_pages: int = 20) -> list[SevdeskPart]:
        rows: list[SevdeskPart] = []
        offset = 0
        for _ in range(max_pages):
            params = {"limit": _PAGE_SIZE, "offset": offset, "embed": "category,unity"}
            try:
                response = self._conn.get("/Part", params=params)
            except Exception as exc:  # noqa: BLE001
                logger.warning("PartClient.list_parts failed at offset %s: %s", offset, exc)
                break
            payload = response.json()
            objects = payload.get("objects") if isinstance(payload, dict) else None
            if not isinstance(objects, list):
                break
            for raw in objects:
                if isinstance(raw, dict):
                    rows.append(_parse_part(raw))
            if len(objects) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
        logger.info("PartClient: fetched %s parts", len(rows))
        return rows

    def find_part_by_sku(self, sku: str) -> SevdeskPart | None:
        """Look up a single Part by its partNumber/SKU via GET /Part?partNumber=…."""
        try:
            response = self._conn.get("/Part", params={"partNumber": sku, "embed": "category,unity"})
            payload = response.json()
            objects = payload.get("objects") if isinstance(payload, dict) else []
            if not isinstance(objects, list) or not objects:
                return None
            for raw in objects:
                if isinstance(raw, dict):
                    return _parse_part(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("find_part_by_sku(%r) failed: %s", sku, exc)
        return None

    def get_part_by_id(self, part_id: str) -> SevdeskPart | None:
        """Fetch one sevDesk part by id."""
        try:
            response = self._conn.get(f"/Part/{str(part_id).strip()}", params={"embed": "category,unity"})
            payload = response.json()
            objects = payload.get("objects") if isinstance(payload, dict) else []
            raw: dict[str, Any] | None = None
            if isinstance(objects, list) and objects and isinstance(objects[0], dict):
                raw = objects[0]
            elif isinstance(objects, dict):
                raw = objects
            elif isinstance(payload, dict):
                raw = payload
            if isinstance(raw, dict):
                return _parse_part(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_part_by_id(%r) failed: %s", part_id, exc)
        return None

    def create_part(self, payload: dict[str, Any]) -> SevdeskPart:
        """Create a new sevDesk part/article."""
        response = self._conn.post("/Part", json=payload)
        raw_payload = response.json() if response.content else {}
        objects = raw_payload.get("objects") if isinstance(raw_payload, dict) else []
        raw: dict[str, Any] | None = None
        if isinstance(objects, list) and objects and isinstance(objects[0], dict):
            raw = objects[0]
        elif isinstance(objects, dict):
            raw = objects
        elif isinstance(raw_payload, dict):
            raw = raw_payload
        if not isinstance(raw, dict):
            raise RuntimeError("sevDesk-Part konnte nicht erstellt werden.")
        created = _parse_part(raw)
        if not created.id.strip():
            raise RuntimeError("sevDesk-Part wurde erstellt, aber ohne ID zurueckgegeben.")
        logger.info("PartClient: created part %s for SKU %s", created.id, created.sku)
        return created

    def list_part_categories(self) -> list[dict[str, str]]:
        """Return sevDesk part categories for ``/Category?objectType=Part``."""
        try:
            response = self._conn.get("/Category", params={"objectType": "Part", "limit": 1000, "offset": 0})
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("PartClient.list_part_categories failed: %s", exc)
            return []

        objects = payload.get("objects") if isinstance(payload, dict) else []
        if not isinstance(objects, list):
            return []

        categories: list[dict[str, str]] = []
        for raw in objects:
            if not isinstance(raw, dict):
                continue
            cat_id = str(raw.get("id") or "").strip()
            name = str(raw.get("name") or raw.get("displayName") or raw.get("categoryName") or "").strip()
            if cat_id and name:
                categories.append({"id": cat_id, "name": name})
        return categories

    def get_part_stock(self, part_id: str) -> int:
        """Return current stock for a single sevDesk Part.

        Uses GET /Part/{partId}/getStock which returns {"objects": <number>}.
        Falls back to full Part fetch if the dedicated endpoint is unavailable.
        """
        try:
            response = self._conn.get(f"/Part/{part_id}/getStock")
            payload = response.json()
            raw_stock = payload.get("objects") if isinstance(payload, dict) else None
            if raw_stock is not None:
                return max(0, int(float(raw_stock)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_part_stock via /getStock failed for %s: %s", part_id, exc)
        # Fallback: full Part fetch
        try:
            response = self._conn.get(f"/Part/{part_id}")
            payload = response.json()
            objects = payload.get("objects") if isinstance(payload, dict) else []
            if isinstance(objects, list) and objects:
                raw = objects[0]
            elif isinstance(objects, dict):
                raw = objects
            else:
                return 0
            return max(0, int(float(raw.get("stock") or 0)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_part_stock fallback failed for %s: %s", part_id, exc)
            return 0

    def set_part_stock(self, part_id: str, new_stock: int) -> None:
        """Write a new stock value to sevDesk via PUT /Part/{partId}.

        sevDesk accepts partial updates — only `stock` is sent.
        """
        try:
            self._conn.put(f"/Part/{part_id}", json={"stock": float(new_stock)})
            logger.info("sevDesk Part %s stock set to %d", part_id, new_stock)
        except Exception as exc:  # noqa: BLE001
            logger.error("set_part_stock failed for Part %s: %s", part_id, exc)
            raise
