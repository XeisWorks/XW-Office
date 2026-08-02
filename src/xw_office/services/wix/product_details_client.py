"""Wix Product Details client — version-aware field updates.

Autodetects whether the connected site uses CATALOG_V1 (Stores v1 product API)
or the newer v3 catalog, then routes each write to the correct endpoint with
the correct payload shape.

v3 differences vs v1
---------------------
- Every PATCH requires the current ``revision`` string (optimistic concurrency).
- Bulk property updates: ``POST /stores/v3/products/bulkUpdateProperty``.
- Bulk percentage adjustments: ``POST /stores/v3/products/bulkAdjustProperty``.

v1 differences
--------------
- PATCH does NOT need ``revision``.
- Bulk operations are done as individual PATCH calls (no dedicated bulk endpoint).
- Field names differ in some cases (e.g. ``compareAtPrice`` vs ``salePrice``).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from xw_office.services.secrets.service import SecretService

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SEC = 0.4
_BULK_CHUNK = 100  # max products per bulk request

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class CatalogVersion(str, Enum):
    """Detected catalog version for the connected Wix site."""

    V3 = "v3"
    V1 = "v1"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProductFieldUpdate:
    """One field/value pair to be written to a product."""

    product_id: str
    field: str
    value: Any  # str, float, bool, list — depends on field
    wix_id: str = ""  # alias; ignored, product_id is authoritative


@dataclass
class UpdateResult:
    """Outcome of a single or bulk update run."""

    requested: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    catalog_version: str = ""


class WixProductDetail(BaseModel):
    """Extended product detail model, richer than the list-level WixProduct."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    revision: str = ""
    name: str = ""
    sku: str = ""
    price: float | None = None
    compare_at_price: float | None = None
    cost: float | None = None
    weight: float | None = None
    visible: bool = True
    description: str = ""
    brand_name: str = ""
    brand_id: str = ""
    ribbon: str = ""
    inventory_quantity: int = 0
    category_ids: list[str] = field(default_factory=list)
    category_names_by_id: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_detail(raw: dict[str, Any]) -> WixProductDetail:
    """Parse a raw Wix product dict into WixProductDetail."""
    pid = str(raw.get("id") or "")
    revision = str(raw.get("revision") or raw.get("_revision") or "")
    name = str(raw.get("name") or "")
    sku = ""
    price: float | None = None
    compare_at_price: float | None = None
    cost: float | None = None
    weight: float | None = None

    # v3 layout
    variants = raw.get("variants") or raw.get("variantsInfo", {}).get("variants") or []
    if isinstance(variants, list) and variants and isinstance(variants[0], dict):
        v = variants[0]
        sku = str(v.get("sku") or "")
        pd = v.get("priceData") or {}
        if isinstance(pd, dict):
            try:
                price = float(pd.get("price") or 0)
            except (TypeError, ValueError):
                pass
            try:
                compare_at_price = float(pd.get("compareAtPrice") or 0) or None
            except (TypeError, ValueError):
                pass

    # v1 layout fallback
    if not sku:
        sku = str(raw.get("sku") or "")
    if price is None:
        try:
            price = float(raw.get("price") or raw.get("priceGross") or 0)
        except (TypeError, ValueError):
            price = None

    # cost / weight — v3 top-level or v1 top-level
    for key in ("cost", "cost_of_goods"):
        val = raw.get(key)
        if val is not None:
            try:
                cost = float(val)
            except (TypeError, ValueError):
                pass
            break
    for key in ("weight", "shippingWeight"):
        val = raw.get(key)
        if val is not None:
            try:
                weight = float(val)
            except (TypeError, ValueError):
                pass
            break

    visible = bool(raw.get("visible", True))
    description = str(raw.get("description") or raw.get("plainDescription") or "")

    raw_brand = raw.get("brand")
    brand_name = ""
    brand_id = ""
    if isinstance(raw_brand, str):
        brand_name = raw_brand.strip()
    elif isinstance(raw_brand, dict):
        brand_name = str(raw_brand.get("name") or "").strip()
        brand_id = str(raw_brand.get("id") or "").strip()
    if not brand_name:
        brand_name = str(raw.get("brandName") or "").strip()

    ribbon_raw = raw.get("ribbon") or raw.get("ribbonText") or ""
    ribbon = str(ribbon_raw).strip() if isinstance(ribbon_raw, str) else ""

    # stock / inventory
    qty = 0
    inv = raw.get("stock") or raw.get("inventoryItem") or {}
    if isinstance(inv, dict):
        try:
            qty = int(inv.get("quantity") or inv.get("totalQuantity") or 0)
        except (TypeError, ValueError):
            pass

    # categories
    raw_cats = raw.get("categories") or raw.get("categoryIds") or raw.get("collectionIds") or []
    category_ids: list[str] = []
    category_names_by_id: dict[str, str] = {}
    if isinstance(raw_cats, list):
        for cat in raw_cats:
            if isinstance(cat, str) and cat.strip():
                category_ids.append(cat.strip())
            elif isinstance(cat, dict):
                cid = str(cat.get("id") or cat.get("categoryId") or "").strip()
                if cid:
                    category_ids.append(cid)
                    category_name = str(
                        cat.get("name")
                        or cat.get("displayName")
                        or cat.get("label")
                        or cat.get("title")
                        or ""
                    ).strip()
                    if category_name:
                        category_names_by_id[cid] = category_name
    main_category_id = str(raw.get("mainCategoryId") or raw.get("main_category_id") or "").strip()
    if main_category_id and main_category_id not in category_ids:
        category_ids.insert(0, main_category_id)
    main_category_raw = raw.get("mainCategory")
    if isinstance(main_category_raw, dict):
        cid = str(main_category_raw.get("id") or main_category_raw.get("categoryId") or main_category_id or "").strip()
        category_name = str(
            main_category_raw.get("name")
            or main_category_raw.get("displayName")
            or main_category_raw.get("label")
            or main_category_raw.get("title")
            or ""
        ).strip()
        if cid and cid not in category_ids:
            category_ids.insert(0, cid)
        if cid and category_name:
            category_names_by_id[cid] = category_name

    return WixProductDetail(
        id=pid,
        revision=revision,
        name=name,
        sku=sku,
        price=price if price else None,
        compare_at_price=compare_at_price,
        cost=cost,
        weight=weight,
        visible=visible,
        description=description,
        brand_name=brand_name,
        brand_id=brand_id,
        ribbon=ribbon,
        inventory_quantity=qty,
        category_ids=category_ids,
        category_names_by_id=category_names_by_id,
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class WixProductDetailsClient:
    """Catalog-version-aware client for reading and updating individual product fields.

    Usage::

        client = WixProductDetailsClient(secret_service=secret_svc)
        # Version is probed lazily on the first write call:
        result = client.update_product_price("abc123", price=19.99)
    """

    _V3_BASE = "https://www.wixapis.com/stores/v3"
    _V1_BASE = "https://www.wixapis.com/stores/v1"

    def __init__(
        self,
        *,
        secret_service: "SecretService | None" = None,
    ) -> None:
        self._secrets = secret_service
        self._detected_version: CatalogVersion | None = None

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    def _api_key(self) -> str:
        return (self._secrets.get_secret("WIX_API_KEY") if self._secrets else "") or ""

    def _site_id(self) -> str:
        return (self._secrets.get_secret("WIX_SITE_ID") if self._secrets else "") or ""

    def _account_id(self) -> str:
        return (self._secrets.get_secret("WIX_ACCOUNT_ID") if self._secrets else "") or ""

    def has_credentials(self) -> bool:
        return bool(self._api_key() and self._site_id())

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._api_key(),
            "wix-site-id": self._site_id(),
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Version detection
    # ------------------------------------------------------------------

    def detect_catalog_version(self, *, force: bool = False) -> CatalogVersion:
        """Probe the site to determine whether it uses CATALOG_V1 or v3.

        Result is cached after the first successful probe.
        Pass ``force=True`` to re-probe.
        """
        if self._detected_version is not None and not force:
            return self._detected_version

        if not self.has_credentials():
            self._detected_version = CatalogVersion.UNKNOWN
            return self._detected_version

        headers = self._headers()
        # A minimal v3 query — if we get HTTP 428 ("wrong catalog version"),
        # the site is on CATALOG_V1.
        probe_url = f"{self._V3_BASE}/catalog/products/query"
        probe_body: dict[str, Any] = {"query": {"paging": {"limit": 1}}}
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(probe_url, headers=headers, json=probe_body)
            if resp.status_code == 428:
                # Wix returns 428 with "CATALOG_V1" when the site uses the old catalog
                self._detected_version = CatalogVersion.V1
            elif resp.status_code < 400:
                self._detected_version = CatalogVersion.V3
            else:
                # Other v3-style paths
                alt_url = f"{self._V3_BASE}/products/query"
                with httpx.Client(timeout=_TIMEOUT) as client:
                    resp2 = client.post(alt_url, headers=headers, json=probe_body)
                self._detected_version = CatalogVersion.V3 if resp2.status_code < 400 else CatalogVersion.V1
        except Exception as exc:  # noqa: BLE001
            logger.warning("WixProductDetailsClient: version probe failed: %s", exc)
            self._detected_version = CatalogVersion.UNKNOWN

        logger.info("WixProductDetailsClient: detected catalog version = %s", self._detected_version.value)
        return self._detected_version

    # ------------------------------------------------------------------
    # Read: get product detail
    # ------------------------------------------------------------------

    def get_product(self, product_id: str) -> WixProductDetail | None:
        """Fetch full product details for one product by ID."""
        pid = str(product_id or "").strip()
        if not pid or not self.has_credentials():
            return None

        version = self.detect_catalog_version()
        urls = self._get_endpoint_candidates(pid, version)
        headers = self._headers()

        with httpx.Client(timeout=_TIMEOUT) as client:
            for url in urls:
                try:
                    resp = client.get(url, headers=headers)
                    if resp.status_code < 400:
                        raw = resp.json() if resp.content else {}
                        product_raw = raw.get("product") or raw
                        if isinstance(product_raw, dict) and product_raw.get("id"):
                            return _parse_detail(product_raw)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("WixProductDetailsClient.get_product %s failed at %s: %s", pid, url, exc)

        logger.warning("WixProductDetailsClient: could not fetch product %s", pid)
        return None

    def get_product_revision(self, product_id: str) -> str:
        """Return the current revision string for a product (needed for v3 updates)."""
        detail = self.get_product(product_id)
        return detail.revision if detail is not None else ""

    def query_category_names(self) -> dict[str, str]:
        """Return Wix category/collection display names by ID.

        Wix uses Catalog V3 categories on newer stores and Stores V1
        collections on older catalogs. The UI presents both as categories.
        """
        if not self.has_credentials():
            return {}
        headers = self._headers()
        endpoints = [
            (f"{self._V3_BASE}/catalog/categories/query", {"query": {"paging": {"limit": 100}}}),
            (f"{self._V3_BASE}/categories/query", {"query": {"paging": {"limit": 100}}}),
            (
                f"{self._V1_BASE}/collections/query",
                {"query": {}, "includeNumberOfProducts": False, "includeDescription": False},
            ),
        ]
        names: dict[str, str] = {}
        with httpx.Client(timeout=_TIMEOUT) as client:
            for url, body in endpoints:
                try:
                    resp = client.post(url, headers=headers, json=body)
                    if resp.status_code >= 400:
                        continue
                    data = resp.json() if resp.content else {}
                except Exception as exc:  # noqa: BLE001 - category fallback must stay best-effort.
                    logger.debug("WixProductDetailsClient category query failed at %s: %s", url, exc)
                    continue
                for raw in self._extract_category_rows(data):
                    cid = str(raw.get("id") or raw.get("categoryId") or "").strip()
                    name = str(
                        raw.get("name")
                        or raw.get("displayName")
                        or raw.get("label")
                        or raw.get("title")
                        or ""
                    ).strip()
                    if cid and name:
                        names[cid] = name
                if names:
                    return names
        return names

    @staticmethod
    def _extract_category_rows(data: object) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        rows: list[dict[str, Any]] = []
        for key in ("categories", "collections", "items", "results"):
            raw_rows = data.get(key)
            if isinstance(raw_rows, list):
                rows.extend(item for item in raw_rows if isinstance(item, dict))
        return rows

    # ------------------------------------------------------------------
    # Write: field-specific update methods
    # ------------------------------------------------------------------

    def update_product_price(self, product_id: str, *, price: float) -> UpdateResult:
        """Set the base price for a product."""
        return self._update_single(product_id, "price", price)

    def update_product_compare_at_price(self, product_id: str, *, compare_at_price: float | None) -> UpdateResult:
        """Set the sale/compare-at price. Pass None to clear it."""
        return self._update_single(product_id, "compareAtPrice", compare_at_price)

    def update_product_cost(self, product_id: str, *, cost: float) -> UpdateResult:
        """Set cost of goods."""
        return self._update_single(product_id, "cost", cost)

    def update_product_weight(self, product_id: str, *, weight: float) -> UpdateResult:
        """Set shipping weight."""
        return self._update_single(product_id, "weight", weight)

    def update_product_visible(self, product_id: str, *, visible: bool) -> UpdateResult:
        """Show or hide a product in the storefront."""
        return self._update_single(product_id, "visible", visible)

    def update_product_name(self, product_id: str, *, name: str) -> UpdateResult:
        """Rename a product."""
        return self._update_single(product_id, "name", str(name))

    def update_product_description(self, product_id: str, *, description: str) -> UpdateResult:
        """Replace the product description (plain HTML/text, no rich-content)."""
        return self._update_single(product_id, "description", str(description))

    def update_product_ribbon(self, product_id: str, *, ribbon: str) -> UpdateResult:
        """Set the ribbon/badge label on a product."""
        return self._update_single(product_id, "ribbon", str(ribbon))

    def update_product_brand(self, product_id: str, *, brand_name: str) -> UpdateResult:
        """Set the product brand name."""
        return self._update_single(product_id, "brand", brand_name)

    # ------------------------------------------------------------------
    # Write: bulk property update
    # ------------------------------------------------------------------

    def bulk_update_property(
        self,
        product_ids: list[str],
        *,
        field: str,
        value: Any,
    ) -> UpdateResult:
        """Set one field on multiple products at once.

        For v3 sites: uses ``POST /bulkUpdateProperty`` (up to 100 per call).
        For v1 sites: falls back to individual PATCH calls.
        """
        ids = [str(pid or "").strip() for pid in product_ids if str(pid or "").strip()]
        if not ids:
            return UpdateResult()
        if not self.has_credentials():
            raise RuntimeError("Wix Credentials fehlen")

        version = self.detect_catalog_version()
        if version == CatalogVersion.V3:
            return self._bulk_update_v3(ids, field=field, value=value)
        return self._bulk_update_v1_loop(ids, field=field, value=value)

    def bulk_adjust_price(
        self,
        product_ids: list[str],
        *,
        adjust_type: str = "PERCENTAGE",
        adjust_value: float,
    ) -> UpdateResult:
        """Adjust price by a percentage or flat amount on multiple products.

        For v3 uses ``bulkAdjustProperty``. For v1 falls back to individual PATCHes
        (requires a pre-fetch of current prices).

        ``adjust_type``: ``"PERCENTAGE"`` or ``"AMOUNT"``.
        """
        ids = [str(pid or "").strip() for pid in product_ids if str(pid or "").strip()]
        if not ids:
            return UpdateResult()
        if not self.has_credentials():
            raise RuntimeError("Wix Credentials fehlen")

        version = self.detect_catalog_version()
        result = UpdateResult(requested=len(ids), catalog_version=version.value)

        if version == CatalogVersion.V3:
            headers = self._headers()
            bulk_url = f"{self._V3_BASE}/products/bulkAdjustProperty"
            for chunk_start in range(0, len(ids), _BULK_CHUNK):
                chunk = ids[chunk_start : chunk_start + _BULK_CHUNK]
                body: dict[str, Any] = {
                    "productIds": chunk,
                    "property": "price",
                    "adjustValue": adjust_value,
                    "adjustType": adjust_type.upper(),
                }
                try:
                    resp = self._do_request("POST", bulk_url, headers=headers, json_body=body)
                    chunk_results = resp.get("results") or []
                    if chunk_results:
                        for r in chunk_results:
                            if isinstance(r, dict) and r.get("error"):
                                result.failed += 1
                                result.errors.append(str(r["error"]))
                            else:
                                result.succeeded += 1
                    else:
                        # Empty results list but no exception → count all as succeeded
                        result.succeeded += len(chunk)
                except Exception as exc:  # noqa: BLE001
                    result.failed += len(chunk)
                    result.errors.append(str(exc))
        else:
            # v1 fallback: fetch-then-patch per product
            for pid in ids:
                detail = self.get_product(pid)
                if detail is None or detail.price is None:
                    result.failed += 1
                    result.errors.append(f"{pid}: Produktpreis nicht abrufbar")
                    continue
                current_price = float(detail.price)
                if adjust_type.upper() == "PERCENTAGE":
                    new_price = round(current_price * (1 + adjust_value / 100), 2)
                else:
                    new_price = round(current_price + adjust_value, 2)
                r = self._update_single(pid, "price", max(0.0, new_price))
                result.succeeded += r.succeeded
                result.failed += r.failed
                result.errors.extend(r.errors)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_single(self, product_id: str, field: str, value: Any) -> UpdateResult:
        """Route a single-product field update to the correct version handler."""
        pid = str(product_id or "").strip()
        if not pid:
            raise ValueError("product_id fehlt")
        if not self.has_credentials():
            raise RuntimeError("Wix Credentials fehlen")

        version = self.detect_catalog_version()
        result = UpdateResult(requested=1, catalog_version=version.value)

        if version == CatalogVersion.V3:
            ok, err = self._patch_v3(pid, field, value)
        else:
            ok, err = self._patch_v1(pid, field, value)

        if ok:
            result.succeeded = 1
        else:
            result.failed = 1
            result.errors.append(err or "unknown")
        return result

    def _patch_v3(self, product_id: str, field: str, value: Any) -> tuple[bool, str]:
        """PATCH via v3 endpoint — requires fetching revision first."""
        revision = self.get_product_revision(product_id)
        payload = self._build_v3_payload(field, value, revision)
        urls = [
            f"{self._V3_BASE}/catalog/products/{product_id}",
            f"{self._V3_BASE}/products/{product_id}",
        ]
        headers = self._headers()
        for url in urls:
            try:
                self._do_request("PATCH", url, headers=headers, json_body=payload)
                logger.info("WixProductDetailsClient v3 PATCH ok: product %s, field %s", product_id, field)
                return True, ""
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 428:
                    # CATALOG_V1 on this endpoint — flip to v1 silently
                    self._detected_version = CatalogVersion.V1
                    return self._patch_v1(product_id, field, value)
                logger.debug("WixProductDetailsClient v3 PATCH failed at %s: %s", url, exc)
            except Exception as exc:  # noqa: BLE001
                logger.debug("WixProductDetailsClient v3 PATCH failed at %s: %s", url, exc)
        return False, f"v3 PATCH fehlgeschlagen fuer Produkt {product_id}"

    def _patch_v1(self, product_id: str, field: str, value: Any) -> tuple[bool, str]:
        """PATCH via v1 endpoint — no revision required."""
        payload = self._build_v1_payload(field, value)
        url = f"{self._V1_BASE}/products/{product_id}"
        headers = self._headers()
        try:
            self._do_request("PATCH", url, headers=headers, json_body=payload)
            logger.info("WixProductDetailsClient v1 PATCH ok: product %s, field %s", product_id, field)
            return True, ""
        except Exception as exc:  # noqa: BLE001
            logger.debug("WixProductDetailsClient v1 PATCH failed: %s", exc)
            return False, str(exc)

    def _bulk_update_v3(self, ids: list[str], *, field: str, value: Any) -> UpdateResult:
        """v3 bulk property update via ``POST /bulkUpdateProperty``."""
        result = UpdateResult(requested=len(ids), catalog_version=CatalogVersion.V3.value)
        headers = self._headers()
        bulk_url = f"{self._V3_BASE}/products/bulkUpdateProperty"
        wix_field = self._v3_field_name(field)

        for chunk_start in range(0, len(ids), _BULK_CHUNK):
            chunk = ids[chunk_start : chunk_start + _BULK_CHUNK]
            body: dict[str, Any] = {
                "productIds": chunk,
                "property": wix_field,
                "value": self._coerce_value(field, value),
            }
            try:
                resp = self._do_request("POST", bulk_url, headers=headers, json_body=body)
                chunk_results = resp.get("results") or []
                for r in chunk_results:
                    if isinstance(r, dict) and r.get("error"):
                        result.failed += 1
                        result.errors.append(str(r["error"]))
                    else:
                        result.succeeded += 1
                # If results is empty but no error, count all as succeeded
                if not chunk_results:
                    result.succeeded += len(chunk)
            except Exception as exc:  # noqa: BLE001
                result.failed += len(chunk)
                result.errors.append(str(exc))

        return result

    def _bulk_update_v1_loop(self, ids: list[str], *, field: str, value: Any) -> UpdateResult:
        """v1 fallback: individual PATCH calls for each product."""
        result = UpdateResult(requested=len(ids), catalog_version=CatalogVersion.V1.value)
        for pid in ids:
            ok, err = self._patch_v1(pid, field, value)
            if ok:
                result.succeeded += 1
            else:
                result.failed += 1
                result.errors.append(f"{pid}: {err}")
        return result

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_v3_payload(field: str, value: Any, revision: str) -> dict[str, Any]:
        """Build a PATCH payload for v3 (with revision, correct field path)."""
        coerced = WixProductDetailsClient._coerce_value(field, value)
        wix_field = WixProductDetailsClient._v3_field_name(field)

        # Fields that live inside a nested dict
        if field == "price":
            inner: dict[str, Any] = {"revision": revision, "priceData": {"price": coerced}}
        elif field == "compareAtPrice":
            inner = {"revision": revision, "priceData": {"compareAtPrice": coerced}}
        elif field == "brand":
            inner = {"revision": revision, "brand": {"name": str(coerced)}}
        elif field == "visible":
            inner = {"revision": revision, "visible": bool(coerced)}
        else:
            inner = {"revision": revision, wix_field: coerced}

        return {"product": inner}

    @staticmethod
    def _build_v1_payload(field: str, value: Any) -> dict[str, Any]:
        """Build a PATCH payload for v1 (no revision needed, slightly different field names)."""
        coerced = WixProductDetailsClient._coerce_value(field, value)
        v1_field = WixProductDetailsClient._v1_field_name(field)

        if field == "price":
            inner: dict[str, Any] = {"priceData": {"price": str(coerced)}}
        elif field == "compareAtPrice":
            inner = {"priceData": {"compareAtPrice": str(coerced)}}
        elif field == "brand":
            inner = {"brand": str(coerced)}
        elif field == "visible":
            inner = {"visible": bool(coerced)}
        else:
            inner = {v1_field: coerced}

        return {"product": inner}

    @staticmethod
    def _coerce_value(field: str, value: Any) -> Any:
        """Coerce a Python value to the expected type for the given field."""
        if field in {"price", "compareAtPrice", "cost", "weight"}:
            if value is None:
                return None
            return round(float(value), 2)
        if field == "visible":
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "ja")
            return bool(value)
        if field == "categories":
            if isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            return list(value) if isinstance(value, (list, tuple)) else [str(value)]
        return value

    @staticmethod
    def _v3_field_name(field: str) -> str:
        """Map canonical field names to v3 API property names."""
        mapping = {
            "compareAtPrice": "compareAtPrice",
            "compare_at_price": "compareAtPrice",
            "cost": "cost",
            "weight": "weight",
            "visible": "visible",
            "name": "name",
            "description": "description",
            "ribbon": "ribbon",
            "brand": "brand",
            "categories": "categories",
            "price": "price",
        }
        return mapping.get(field, field)

    @staticmethod
    def _v1_field_name(field: str) -> str:
        """Map canonical field names to v1 API property names (differ slightly)."""
        mapping = {
            "compareAtPrice": "salePrice",
            "compare_at_price": "salePrice",
            "cost": "costOfGoodsSold",
            "weight": "weight",
            "visible": "visible",
            "name": "name",
            "description": "description",
            "ribbon": "ribbon",
            "brand": "brand",
            "categories": "categoryIds",
            "price": "price",
        }
        return mapping.get(field, field)

    def _get_endpoint_candidates(self, product_id: str, version: CatalogVersion) -> list[str]:
        """Return ordered GET endpoint candidates for a product."""
        if version == CatalogVersion.V3:
            return [
                f"{self._V3_BASE}/catalog/products/{product_id}",
                f"{self._V3_BASE}/products/{product_id}",
                f"{self._V1_BASE}/products/{product_id}",
            ]
        return [
            f"{self._V1_BASE}/products/{product_id}",
            f"{self._V3_BASE}/catalog/products/{product_id}",
        ]

    def _do_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request with retry logic; raises on non-2xx."""
        last_error: Exception | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                with httpx.Client(timeout=_TIMEOUT) as client:
                    resp = client.request(method, url, headers=headers, json=json_body)
                if resp.status_code >= 400:
                    if resp.status_code in (408, 429, 500, 502, 503, 504) and attempt < _RETRY_ATTEMPTS:
                        time.sleep(_RETRY_BACKOFF_SEC * attempt)
                        continue
                    resp.raise_for_status()
                return resp.json() if resp.content else {}
            except httpx.HTTPStatusError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < _RETRY_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF_SEC * attempt)
                    continue
                break
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{method} {url} failed without exception")
