"""Wix Store REST client — products and order status."""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict

from xw_studio.services.shipping.countries import country_label_for_address, country_name_en
from xw_studio.services.wix.order_cache import WixOrderCache

if TYPE_CHECKING:
    from xw_studio.services.secrets.service import SecretService

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_PRODUCTS_PAGE_SIZE = 100
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SEC = 0.35

_ORDERS_BASE = "https://www.wixapis.com/ecom/v1"
_UNRELEASED_PREFIXES = ("XW-600", "XW-010")


class CancellationToken(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


class WixProduct(BaseModel):
    """Minimal Wix Catalog product row for sync."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    sku: str = ""
    price: str = ""
    brand_name: str = ""
    brand_id: str = ""
    visible: bool = True
    inventory_quantity: int = 0


def _parse_product(raw: dict[str, Any]) -> WixProduct:
    pid = str(raw.get("id") or "")
    name = str(raw.get("name") or "")
    sku = ""
    price = ""
    variants: list[Any] = raw.get("variants") or []
    if variants and isinstance(variants[0], dict):
        v = variants[0]
        sku = str(v.get("sku") or "")
        pricing = v.get("priceData") or {}
        if isinstance(pricing, dict):
            price = str(pricing.get("price") or "")
    if not sku:
        sku = str(raw.get("sku") or "")
    brand_name = ""
    brand_id = ""
    raw_brand = raw.get("brand")
    if isinstance(raw_brand, str):
        brand_name = raw_brand.strip()
    elif isinstance(raw_brand, dict):
        brand_name = str(raw_brand.get("name") or raw_brand.get("label") or "").strip()
        brand_id = str(raw_brand.get("id") or "").strip()
    if not brand_name:
        brand_name = str(raw.get("brandName") or "").strip()
    if not brand_id:
        brand_id = str(raw.get("brandId") or "").strip()
    visible = bool(raw.get("visible", True))
    inv = raw.get("stock") or {}
    qty = 0
    if isinstance(inv, dict):
        try:
            qty = int(inv.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
    return WixProduct(
        id=pid,
        name=name,
        sku=sku,
        price=price,
        brand_name=brand_name,
        brand_id=brand_id,
        visible=visible,
        inventory_quantity=qty,
    )


class WixProductsClient:
    """Read Wix Stores Catalog (v3) products.

    Credentials come from :class:`SecretService` (DB/env):
    - WIX_API_KEY  — bearer token
    - WIX_SITE_ID  — target site
    - WIX_ACCOUNT_ID — (optional) Wix account header
    """

    def __init__(
        self,
        *,
        secret_service: "SecretService | None" = None,
        base_url: str = "https://www.wixapis.com/stores/v3",
    ) -> None:
        self._secrets = secret_service
        self._base_url = base_url.rstrip("/")
        self._brand_catalog_supported: bool | None = None

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    def _api_key(self) -> str:
        if self._secrets:
            return self._secrets.get_secret("WIX_API_KEY") or ""
        return ""

    def _site_id(self) -> str:
        if self._secrets:
            return self._secrets.get_secret("WIX_SITE_ID") or ""
        return ""

    def _account_id(self) -> str:
        if self._secrets:
            return self._secrets.get_secret("WIX_ACCOUNT_ID") or ""
        return ""

    def has_credentials(self) -> bool:
        return bool(self._api_key() and self._site_id())

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Authorization": self._api_key(),
            "wix-site-id": self._site_id(),
            "Content-Type": "application/json",
        }
        account_id = self._account_id()
        if account_id:
            headers["wix-account-id"] = account_id
        return headers

    def _brand_endpoint_candidates(self, suffix: str) -> list[str]:
        base_v3 = self._base_url.rstrip("/")
        # Keep fallbacks broad because Wix API surfaces differ between accounts/versions.
        candidates = [
            f"{base_v3}/brands{suffix}",
            f"{base_v3}/catalog/brands{suffix}",
            "https://www.wixapis.com/stores/v1/brands" + suffix,
            "https://www.wixapis.com/ecom/v1/brands" + suffix,
        ]
        # Preserve order while removing duplicates.
        return list(dict.fromkeys(candidates))

    def _product_query_endpoint_candidates(self) -> list[str]:
        base_v3 = self._base_url.rstrip("/")
        candidates = [
            f"{base_v3}/catalog/products/query",
            f"{base_v3}/products/query",
            "https://www.wixapis.com/stores/v1/products/query",
            "https://www.wixapis.com/ecom/v1/products/query",
        ]
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _extract_product_list(data: object) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        candidates = [
            data.get("products"),
            data.get("items"),
            data.get("results"),
        ]
        for raw in candidates:
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_next_cursor(data: object) -> str | None:
        if not isinstance(data, dict):
            return None
        for meta_key in ("metadata", "pagingMetadata"):
            meta = data.get(meta_key)
            if not isinstance(meta, dict):
                continue
            cursors = meta.get("cursors")
            if isinstance(cursors, dict):
                nxt = str(cursors.get("next") or "").strip()
                if nxt:
                    return nxt
            nxt_direct = str(meta.get("nextCursor") or "").strip()
            if nxt_direct:
                return nxt_direct
        paging = data.get("paging")
        if isinstance(paging, dict):
            nxt = str(paging.get("nextCursor") or paging.get("next") or "").strip()
            if nxt:
                return nxt
        return None

    @staticmethod
    def _extract_has_next(data: object) -> bool:
        if not isinstance(data, dict):
            return False
        for meta_key in ("metadata", "pagingMetadata", "paging"):
            meta = data.get(meta_key)
            if not isinstance(meta, dict):
                continue
            for key in ("hasNext", "has_next", "nextPage"):
                value = meta.get(key)
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    normalized = value.strip().lower()
                    if normalized in {"true", "1", "yes", "ja", "on"}:
                        return True
                    if normalized in {"false", "0", "no", "nein", "off"}:
                        return False
        return False

    @staticmethod
    def _is_retryable_status(code: int) -> bool:
        return code in (408, 409, 425, 429, 500, 502, 503, 504)

    def _request_with_retry(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            try:
                resp = client.request(method, url, headers=headers, json=json_body)
                if resp.status_code >= 400:
                    if self._is_retryable_status(resp.status_code) and attempt < _RETRY_ATTEMPTS:
                        self._sleep_retry(_RETRY_BACKOFF_SEC * attempt, cancel_token)
                        continue
                    resp.raise_for_status()
                return resp
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _RETRY_ATTEMPTS:
                    self._sleep_retry(_RETRY_BACKOFF_SEC * attempt, cancel_token)
                    continue
                break
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"HTTP request failed without explicit error: {method} {url}")

    @staticmethod
    def _sleep_retry(delay: float, cancel_token: CancellationToken | None) -> None:
        end_at = time.monotonic() + max(0.0, float(delay))
        while time.monotonic() < end_at:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            time.sleep(min(0.1, max(0.0, end_at - time.monotonic())))

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    def list_products(
        self,
        *,
        include_hidden: bool = True,
        cancel_token: CancellationToken | None = None,
    ) -> list[WixProduct]:
        """Fetch all products from Wix Catalog (paginated).

        Returns an empty list when credentials are not configured — no exception.
        """
        if not self.has_credentials():
            logger.info("WixProductsClient: no credentials — returning empty list")
            return []

        headers = self._build_headers()

        results: list[WixProduct] = []
        max_pages = 50
        endpoints = self._product_query_endpoint_candidates()

        with httpx.Client(timeout=_TIMEOUT) as client:
            chosen_endpoint = ""
            for endpoint in endpoints:
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                try:
                    probe = self._request_with_retry(
                        client,
                        "POST",
                        endpoint,
                        headers=headers,
                        json_body={"query": {"paging": {"limit": 1}}},
                        cancel_token=cancel_token,
                    )
                    data_probe = probe.json() if probe.content else {}
                    if self._extract_product_list(data_probe) or probe.status_code < 400:
                        chosen_endpoint = endpoint
                        break
                except Exception as exc:  # noqa: BLE001
                    logger.info("WixProductsClient: product endpoint probe failed %s: %s", endpoint, exc)

            if not chosen_endpoint:
                logger.error("WixProductsClient: no working product query endpoint found")
                return []

            logger.info("WixProductsClient: using product query endpoint %s", chosen_endpoint)

            cursor: str | None = None
            seen_cursors: set[str] = set()
            seen_product_ids: set[str] = set()
            offset = 0
            page = 0
            while page < max_pages:
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                body: dict[str, Any] = {
                    "query": {
                        "paging": {
                            "limit": _PRODUCTS_PAGE_SIZE,
                            **({"offset": offset} if offset > 0 else {}),
                        }
                    }
                }
                if cursor:
                    body["query"]["cursorPaging"] = {"cursor": cursor}

                try:
                    resp = self._request_with_retry(
                        client,
                        "POST",
                        chosen_endpoint,
                        headers=headers,
                        json_body=body,
                        cancel_token=cancel_token,
                    )
                except Exception:
                    logger.exception("WixProductsClient: HTTP error on page %s", page)
                    break

                data = resp.json() if resp.content else {}
                products = self._extract_product_list(data)
                count_before = len(results)
                for raw in products:
                    if cancel_token is not None:
                        cancel_token.raise_if_cancelled()
                    parsed = _parse_product(raw)
                    pid = str(parsed.id or "").strip()
                    if pid:
                        if pid in seen_product_ids:
                            continue
                        seen_product_ids.add(pid)
                    results.append(parsed)
                new_items_added = len(results) - count_before

                if not products:
                    break

                next_cursor = self._extract_next_cursor(data)
                has_next = self._extract_has_next(data)

                if next_cursor:
                    if next_cursor in seen_cursors:
                        break
                    seen_cursors.add(next_cursor)
                    cursor = next_cursor
                    page += 1
                    continue

                if has_next:
                    cursor = None
                    offset += len(products)
                    page += 1
                    continue

                # Some Wix endpoints return full pages without cursor/hasNext metadata.
                # In that case, continue with offset while new items are still discovered.
                if len(products) >= _PRODUCTS_PAGE_SIZE and new_items_added > 0:
                    cursor = None
                    offset += len(products)
                    page += 1
                    continue

                page += 1
                break

        logger.info("WixProductsClient: fetched %s products", len(results))
        return results

    def update_product_brand(self, product_id: str, *, brand_name: str, brand_id: str = "") -> None:
        """Update Wix product brand (best-effort payload compatibility).

        Uses Stores Product APIs (not Stores/Products collection writes).
        """
        pid = str(product_id or "").strip()
        name = str(brand_name or "").strip()
        bid = str(brand_id or "").strip()
        if not pid:
            raise ValueError("Wix product_id fehlt")
        if not name:
            raise ValueError("Brand-Name fehlt")
        if not self.has_credentials():
            raise RuntimeError("Wix Credentials fehlen")

        headers = self._build_headers()
        payload_candidates: list[dict[str, Any]] = [
            {"product": {"brand": {"name": name, **({"id": bid} if bid else {})}}},
            {"product": {"brand": name}},
            {"product": {"brandName": name, **({"brandId": bid} if bid else {})}},
        ]
        endpoint_candidates = [
            f"{self._base_url}/products/{pid}",
            f"{self._base_url}/catalog/products/{pid}",
            f"https://www.wixapis.com/stores/v1/products/{pid}",
        ]

        last_error: Exception | None = None
        with httpx.Client(timeout=_TIMEOUT) as client:
            for endpoint in endpoint_candidates:
                for payload in payload_candidates:
                    try:
                        self._request_with_retry(
                            client,
                            "PATCH",
                            endpoint,
                            headers=headers,
                            json_body=payload,
                        )
                        logger.info("Wix brand updated for product %s", pid)
                        return
                    except httpx.HTTPError as exc:
                        last_error = exc
                        continue
        if last_error is not None:
            raise RuntimeError(f"Wix Brand-Update fehlgeschlagen fuer Produkt {pid}: {last_error}") from last_error
        raise RuntimeError(f"Wix Brand-Update fehlgeschlagen fuer Produkt {pid}")

    def list_brands(self) -> list[dict[str, str]]:
        """Fetch Wix brands (best-effort across possible API paths)."""
        if not self.has_credentials():
            return []

        headers = self._build_headers()
        endpoints = [
            ("POST", endpoint, {"query": {"paging": {"limit": 100}}})
            for endpoint in self._brand_endpoint_candidates("/query")
        ]

        with httpx.Client(timeout=_TIMEOUT) as client:
            for method, url, payload in endpoints:
                try:
                    resp = self._request_with_retry(client, method, url, headers=headers, json_body=payload)
                    data = resp.json() if resp.content else {}
                    raw: object = []
                    if isinstance(data, dict):
                        raw = data.get("brands")
                        if not isinstance(raw, list):
                            raw = data.get("items")
                        if not isinstance(raw, list):
                            raw = data.get("results")
                    if not isinstance(raw, list):
                        continue
                    out: list[dict[str, str]] = []
                    for item in raw:
                        if not isinstance(item, dict):
                            continue
                        bid = str(item.get("id") or "").strip()
                        name = str(item.get("name") or item.get("label") or "").strip()
                        if name:
                            out.append({"id": bid, "name": name})
                    return out
                except Exception as exc:  # noqa: BLE001
                    logger.info("Wix list_brands endpoint failed %s: %s", url, exc)
                    continue
        return []

    def supports_brand_catalog(self, *, force: bool = False) -> bool:
        """Return whether this Wix site appears to expose a usable brand catalog API.

        This check is intentionally quiet: it probes the known brand query endpoints
        without logging per-endpoint failures, so CATALOG_V1 sites do not spam the log
        when brand updates can already succeed by name-only PATCH.
        """
        if self._brand_catalog_supported is not None and not force:
            return self._brand_catalog_supported
        if not self.has_credentials():
            self._brand_catalog_supported = False
            return self._brand_catalog_supported

        headers = self._build_headers()
        with httpx.Client(timeout=_TIMEOUT) as client:
            for endpoint in self._brand_endpoint_candidates("/query"):
                try:
                    resp = client.request("POST", endpoint, headers=headers, json={"query": {"paging": {"limit": 1}}})
                    if resp.status_code < 400:
                        self._brand_catalog_supported = True
                        return True
                except Exception:
                    continue
        self._brand_catalog_supported = False
        return False


    def update_product_field(self, product_id: str, field_name: str, value: str) -> None:
        """Update a single product field via PATCH (generic, best-effort).

        Supports: price, name, description, weight, visible, etc.
        Tries v3 and v1 endpoints with multiple payload variants.
        """
        pid = str(product_id or "").strip()
        fname = str(field_name or "").strip()
        val = str(value or "").strip()
        if not pid:
            raise ValueError("Wix product_id fehlt")
        if not fname:
            raise ValueError("Field-Name fehlt")
        if not self.has_credentials():
            raise RuntimeError("Wix Credentials fehlen")

        headers = self._build_headers()

        # Build payload variants for common fields
        payload_candidates: list[dict[str, Any]] = []

        if fname in ("price", "compareAtPrice", "cost", "weight"):
            # Numeric fields - try nested structure first
            try:
                num_val = float(val)
                payload_candidates.append({"product": {fname: num_val}})
            except (ValueError, TypeError):
                pass
        
        if fname == "price":
            payload_candidates.extend([
                {"product": {"priceData": {"price": val}}},
                {"product": {"variants": [{"priceData": {"price": val}}]}},
            ])
        elif fname == "visible":
            # Convert boolean string
            bool_val = val.lower() in ("true", "1", "yes", "ja")
            payload_candidates.append({"product": {"visible": bool_val}})
        elif fname == "name":
            payload_candidates.append({"product": {"name": val}})
        elif fname == "description":
            payload_candidates.append({"product": {"description": val}})
        elif fname == "categories":
            # categories may be an array
            payload_candidates.append({"product": {"categories": val.split(",")}})
        
        # Fallback: generic nested structure
        payload_candidates.append({"product": {fname: val}})

        endpoint_candidates = [
            f"{self._base_url}/products/{pid}",
            f"{self._base_url}/catalog/products/{pid}",
            f"https://www.wixapis.com/stores/v1/products/{pid}",
        ]

        last_error: Exception | None = None
        with httpx.Client(timeout=_TIMEOUT) as client:
            for endpoint in endpoint_candidates:
                for payload in payload_candidates:
                    try:
                        self._request_with_retry(
                            client,
                            "PATCH",
                            endpoint,
                            headers=headers,
                            json_body=payload,
                        )
                        logger.info("Wix field updated: product %s, field %s = %s", pid, fname, val)
                        return
                    except httpx.HTTPError as exc:
                        last_error = exc
                        continue
        
        if last_error is not None:
            raise RuntimeError(
                f"Wix field update failed for product {pid}, field {fname}: {last_error}"
            ) from last_error
        raise RuntimeError(f"Wix field update failed for product {pid}, field {fname}")

    def create_brand(self, brand_name: str) -> str:
        """Create a Wix brand and return its ID when available."""
        name = str(brand_name or "").strip()
        if not name:
            raise ValueError("Brand-Name fehlt")
        if not self.has_credentials():
            raise RuntimeError("Wix Credentials fehlen")

        headers = self._build_headers()
        endpoints = []
        for endpoint in self._brand_endpoint_candidates(""):
            endpoints.append(("POST", endpoint, {"brand": {"name": name}}))
            endpoints.append(("POST", endpoint, {"name": name}))

        last_error: Exception | None = None
        with httpx.Client(timeout=_TIMEOUT) as client:
            for method, url, payload in endpoints:
                try:
                    resp = self._request_with_retry(client, method, url, headers=headers, json_body=payload)
                    data = resp.json() if resp.content else {}
                    brand_obj: dict[str, Any] = {}
                    if isinstance(data, dict):
                        if isinstance(data.get("brand"), dict):
                            brand_obj = data.get("brand")
                        elif isinstance(data.get("item"), dict):
                            brand_obj = data.get("item")
                        else:
                            brand_obj = data
                    bid = str(brand_obj.get("id") or "").strip()
                    if bid:
                        return bid
                    # Some endpoints may create by name but not return ID; resolve again.
                    for item in self.list_brands():
                        if str(item.get("name") or "").strip().casefold() == name.casefold():
                            return str(item.get("id") or "").strip()
                    return ""
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.info("Wix create_brand endpoint failed %s: %s", url, exc)
                    continue
        if last_error is not None:
            raise RuntimeError(f"Wix Brand konnte nicht erstellt werden: {last_error}") from last_error
        raise RuntimeError("Wix Brand konnte nicht erstellt werden")

    def ensure_brand(self, brand_name: str, *, create_if_missing: bool = True) -> str:
        """Resolve a Wix brand by name, optionally create when missing."""
        name = str(brand_name or "").strip()
        if not name:
            return ""
        for item in self.list_brands():
            if str(item.get("name") or "").strip().casefold() == name.casefold():
                return str(item.get("id") or "").strip()
        if not create_if_missing:
            return ""
        return self.create_brand(name)


class WixOrderItem(BaseModel):
    """Single line item from a Wix order — used in the Stücke panel."""

    model_config = ConfigDict(extra="ignore")

    line_item_id: str = ""
    sku: str = ""
    name: str = ""
    qty: int = 1
    note: str = ""
    unit_price_gross: float = 0.0
    currency: str = "EUR"
    unit_weight_kg: float = 0.0
    is_unreleased: bool = False


def _wix_text(value: object) -> str:
    if isinstance(value, dict):
        for key in (
            "translated",
            "original",
            "value",
            "name",
            "label",
            "title",
            "text",
        ):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _format_option_entry(entry: object) -> str:
    if isinstance(entry, dict):
        label = _wix_text(
            entry.get("name")
            or entry.get("optionName")
            or entry.get("label")
            or entry.get("key")
        )
        value = _wix_text(
            entry.get("value")
            or entry.get("optionValue")
            or entry.get("selection")
            or entry.get("choice")
            or entry.get("plainText")
        )
        if label and value:
            return f"{label}: {value}"
        return value or label
    return _wix_text(entry)


def _option_lines(source: object) -> list[str]:
    lines: list[str] = []
    if isinstance(source, list):
        for entry in source:
            text = _format_option_entry(entry)
            if text:
                lines.append(text)
        return lines
    if isinstance(source, dict):
        for key, value in source.items():
            if key in {"id", "sku", "code"}:
                continue
            value_text = _wix_text(value)
            key_text = _wix_text(key)
            if key_text and value_text:
                lines.append(f"{key_text}: {value_text}")
            elif value_text:
                lines.append(value_text)
        return lines
    text = _wix_text(source)
    return [text] if text else []


def _line_item_note(raw: dict[str, Any]) -> str:
    def sanitize(lines: list[str]) -> list[str]:
        cleaned: list[str] = []
        for line in lines:
            text = str(line or "").strip()
            if not text:
                continue
            if "rabatt" in text.casefold():
                continue
            cleaned.append(text)
        return cleaned

    # Primary source: Wix option payloads (captures "Besetzung"-like variants)
    for key in ("productOptions", "productOption", "productVariations", "productVariation"):
        lines = sanitize(_option_lines(raw.get(key)))
        if lines:
            return " | ".join(lines)

    # Fallback: legacy description lines
    desc = raw.get("descriptionLines") or []
    if isinstance(desc, list):
        parts: list[str] = []
        for entry in desc:
            if not isinstance(entry, dict):
                continue
            label = _wix_text(entry.get("name"))
            value_obj = entry.get("plainText") or entry.get("colorInfo") or {}
            value = _wix_text(value_obj)
            if label and value:
                parts.append(f"{label}: {value}")
            elif value:
                parts.append(value)
        filtered = sanitize(parts)
        return " | ".join(filtered)
    return ""


def _parse_order_line_item(raw: dict[str, Any]) -> WixOrderItem:
    """Extract a normalized WixOrderItem from a Wix ecom lineItem dict."""
    line_item_id = str(raw.get("id") or "").strip()
    # SKU is nested: physicalProperties.sku or catalogReference.catalogItemOptions.sku
    sku = ""
    phys = raw.get("physicalProperties")
    if isinstance(phys, dict):
        sku = str(phys.get("sku") or "").strip()
    if not sku:
        cat = raw.get("catalogReference") or {}
        if isinstance(cat, dict):
            opts = cat.get("catalogItemOptions") or {}
            if isinstance(opts, dict):
                sku = str(opts.get("sku") or "").strip()

    # Product name
    product_name = raw.get("productName") or {}
    if isinstance(product_name, dict):
        name = str(product_name.get("translated") or product_name.get("original") or "").strip()
    else:
        name = str(product_name or raw.get("name") or raw.get("title") or "").strip()
    if not name and sku:
        name = sku

    # Quantity
    try:
        qty = int(raw.get("quantity") or 1)
    except (TypeError, ValueError):
        qty = 1
    qty = max(qty, 1)

    # Gross line-item price is required when a non-EU PLC label needs customs
    # declarations. Wix has used several representations across API versions.
    unit_price_gross = 0.0
    currency = "EUR"
    for key in ("price", "lineItemPrice", "priceBeforeDiscountsAndTax", "priceBeforeDiscounts"):
        candidate = raw.get(key)
        if isinstance(candidate, dict):
            candidate = candidate.get("amount") or candidate.get("value") or candidate.get("price")
        try:
            parsed = float(str(candidate).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            unit_price_gross = parsed
            break
    for key in ("currency", "currencyCode"):
        value = str(raw.get(key) or "").strip().upper()
        if value:
            currency = value
            break
    unit_weight_kg = 0.0
    raw_weight = phys.get("weight") if isinstance(phys, dict) else None
    if isinstance(raw_weight, dict):
        raw_weight = raw_weight.get("value") or raw_weight.get("amount")
    try:
        unit_weight_kg = max(float(str(raw_weight).replace(",", ".")), 0.0)
    except (TypeError, ValueError):
        pass

    note = _line_item_note(raw)

    is_unreleased = any(sku.upper().startswith(p) for p in _UNRELEASED_PREFIXES)

    return WixOrderItem(
        line_item_id=line_item_id,
        sku=sku,
        name=name,
        qty=qty,
        note=note,
        unit_price_gross=unit_price_gross,
        currency=currency,
        unit_weight_kg=unit_weight_kg,
        is_unreleased=is_unreleased,
    )


class WixOrdersClient:
    """Fetch Wix ecom orders and their line items.

    Credentials from :class:`SecretService` (same keys as WixProductsClient).
    """

    def __init__(
        self,
        *,
        secret_service: "SecretService | None" = None,
        orders_base: str = _ORDERS_BASE,
        order_cache: WixOrderCache | None = None,
    ) -> None:
        self._secrets = secret_service
        self._orders_base = orders_base.rstrip("/")
        self._order_cache = order_cache

    def _api_key(self) -> str:
        return self._secrets.get_secret("WIX_API_KEY") if self._secrets else ""

    def _site_id(self) -> str:
        return self._secrets.get_secret("WIX_SITE_ID") if self._secrets else ""

    def _account_id(self) -> str:
        return self._secrets.get_secret("WIX_ACCOUNT_ID") if self._secrets else ""

    def has_credentials(self) -> bool:
        return bool(self._api_key() and self._site_id())

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Authorization": self._api_key(),
            "wix-site-id": self._site_id(),
            "Content-Type": "application/json",
        }
        acc = self._account_id()
        if acc:
            h["wix-account-id"] = acc
        return h

    @staticmethod
    def _extract_text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            for key in (
                "name",
                "displayName",
                "value",
                "label",
                "shortName",
                "country",
                "code",
                "translated",
                "original",
            ):
                candidate = value.get(key)
                if candidate is not None:
                    text = str(candidate).strip()
                    if text:
                        return text
            return ""
        return str(value).strip()

    @classmethod
    def _nested_dict(cls, source: object, *path: str) -> dict[str, Any]:
        current = source
        for key in path:
            if not isinstance(current, dict):
                return {}
            current = current.get(key)
        return current if isinstance(current, dict) else {}

    @classmethod
    def _first_address_node(cls, order: dict[str, Any]) -> dict[str, Any]:
        paths = (
            ("shippingInfo", "shippingAddress"),
            ("shippingInfo", "address"),
            ("shippingInfo", "shippingDestination", "address"),
            ("shippingInfo", "deliveryAddress"),
            ("shippingInfo", "logistics", "shippingDestination", "address"),
        )
        for path in paths:
            node = cls._nested_dict(order, *path)
            if node:
                return node
        return {}

    @classmethod
    def _resolve_country_name(cls, value: object) -> str:
        return country_name_en(value)

    @classmethod
    def _street_line_from_value(cls, value: object) -> str:
        if isinstance(value, dict):
            name = cls._extract_text(value.get("name"))
            number = cls._extract_text(value.get("number"))
            apt = cls._extract_text(value.get("apt"))
            parts = [part for part in (name, number) if part]
            line = " ".join(parts).strip()
            if apt:
                line = " ".join(part for part in (line, apt) if part).strip()
            return line
        return cls._extract_text(value)

    @staticmethod
    def _looks_like_numeric_address_addition(value: str) -> bool:
        text = str(value or "").strip()
        return bool(re.match(r"^\d[\w\s./-]*$", text))

    @staticmethod
    def _contains_house_number(value: str) -> bool:
        return bool(re.search(r"\d", str(value or "")))

    @classmethod
    def _merge_street_with_addition(cls, street1: str, street2: str) -> tuple[str, str]:
        primary = str(street1 or "").strip().rstrip(",")
        addition = str(street2 or "").strip().rstrip(",")
        if primary and addition and not cls._contains_house_number(primary) and cls._looks_like_numeric_address_addition(addition):
            return " ".join(part for part in (primary, addition) if part).strip(), ""
        return primary, addition

    @classmethod
    def _address_field(cls, *sources: object, keys: tuple[str, ...]) -> str:
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in keys:
                raw_value = source.get(key)
                if key in {"addressLine1", "addressLine", "streetAddress", "street", "address"}:
                    text = cls._street_line_from_value(raw_value)
                else:
                    text = cls._extract_text(raw_value)
                if text:
                    return text
        return ""

    @classmethod
    def _shipping_address_parts_from_order(cls, order: dict[str, Any]) -> dict[str, str]:
        if not isinstance(order, dict):
            return {}
        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
        shipping = order.get("shippingInfo") if isinstance(order.get("shippingInfo"), dict) else {}
        shipment_details = shipping.get("shipmentDetails") if isinstance(shipping.get("shipmentDetails"), dict) else {}
        destination = shipping.get("shippingDestination") if isinstance(shipping.get("shippingDestination"), dict) else {}
        destination_address = destination.get("address") if isinstance(destination.get("address"), dict) else {}
        destination_contact = destination.get("contactDetails") if isinstance(destination.get("contactDetails"), dict) else {}
        logistics_destination = cls._nested_dict(order, "shippingInfo", "logistics", "shippingDestination")
        logistics_address = logistics_destination.get("address") if isinstance(logistics_destination.get("address"), dict) else {}
        logistics_contact = logistics_destination.get("contactDetails") if isinstance(logistics_destination.get("contactDetails"), dict) else {}
        address_node = cls._first_address_node(order)

        first = cls._address_field(
            shipment_details,
            destination_contact,
            logistics_contact,
            buyer,
            shipping,
            keys=("firstName", "givenName", "firstname", "givenname", "surename", "name"),
        )
        last = cls._address_field(
            shipment_details,
            destination_contact,
            logistics_contact,
            buyer,
            shipping,
            keys=("lastName", "familyName", "familyname", "surname", "lastname"),
        )
        company = cls._address_field(
            shipment_details,
            destination_contact,
            logistics_contact,
            shipping,
            keys=("company", "companyName", "businessName", "addressName"),
        )
        person_name = " ".join(part for part in (first, last) if part).strip()
        if not person_name:
            person_name = cls._norm_text(buyer.get("firstName"))
            fallback_last = cls._norm_text(buyer.get("lastName"))
            if fallback_last and fallback_last not in person_name:
                person_name = " ".join(part for part in (person_name, fallback_last) if part).strip()
        if company and person_name and company.casefold() == person_name.casefold():
            company = ""
        name = company or person_name

        street1 = cls._address_field(
            destination_address,
            logistics_address,
            address_node,
            destination,
            logistics_destination,
            shipping,
            keys=("addressLine1", "addressLine", "streetAddress", "street", "address"),
        )
        house = cls._address_field(
            destination_address,
            logistics_address,
            address_node,
            destination,
            logistics_destination,
            shipping,
            keys=("houseNumber", "streetNumber", "addressNumber"),
        )
        if house and house not in street1:
            street1 = " ".join(part for part in (street1, house) if part).strip()
        street2 = cls._address_field(
            destination_address,
            logistics_address,
            address_node,
            destination,
            logistics_destination,
            shipping,
            keys=("addressLine2", "addressAddition", "addressDetail"),
        )
        street1, street2 = cls._merge_street_with_addition(street1, street2)
        postal_code = cls._address_field(
            destination_address,
            logistics_address,
            address_node,
            destination,
            logistics_destination,
            shipping,
            keys=("postalCode", "zipCode", "zip"),
        )
        city = cls._address_field(
            destination_address,
            logistics_address,
            address_node,
            destination,
            logistics_destination,
            shipping,
            keys=("city", "town", "region", "locality"),
        )
        country = cls._resolve_country_name(
            cls._address_field(
                destination_address,
                logistics_address,
                address_node,
                destination,
                logistics_destination,
                shipping,
                keys=("countryFullname", "country", "countryName", "countryCode", "isoCountry", "addressCountry"),
            )
        )
        return {
            "name": name,
            "company": company,
            "person_name": person_name,
            "street1": street1,
            "street2": street2,
            "postal_code": postal_code,
            "city": city,
            "country": country,
        }

    @classmethod
    def _billing_address_parts_from_order(cls, order: dict[str, Any]) -> dict[str, str]:
        if not isinstance(order, dict):
            return {}
        billing = order.get("billingInfo") if isinstance(order.get("billingInfo"), dict) else {}
        details = billing.get("contactDetails") if isinstance(billing.get("contactDetails"), dict) else {}
        address = billing.get("address") if isinstance(billing.get("address"), dict) else {}
        first = cls._address_field(details, keys=("firstName", "givenName", "surename"))
        last = cls._address_field(details, keys=("lastName", "familyName", "familyname"))
        company = cls._address_field(details, billing, keys=("company", "companyName", "businessName"))
        name = company or " ".join(part for part in (first, last) if part).strip()
        street1 = cls._address_field(address, keys=("addressLine1", "addressLine", "streetAddress", "street", "address"))
        street2 = cls._address_field(address, keys=("addressLine2", "addressAddition", "addressDetail"))
        street1, street2 = cls._merge_street_with_addition(street1, street2)
        postal_code = cls._address_field(address, keys=("postalCode", "zipCode", "zip"))
        city = cls._address_field(address, keys=("city", "town", "region", "locality"))
        country = cls._resolve_country_name(
            cls._address_field(address, keys=("countryFullname", "country", "countryName", "countryCode", "isoCountry", "addressCountry"))
        )
        return {
            "name": name,
            "street1": street1,
            "street2": street2,
            "postal_code": postal_code,
            "city": city,
            "country": country,
        }

    def _get_order_by_id(self, order_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.get(
                    f"{self._orders_base}/orders/{order_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                payload = resp.json()
                return payload.get("order") or payload or {}
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient GET order/%s failed: %s", order_id, exc)
                return {}

    def _search_order_by_field(self, field: str, value: str) -> dict[str, Any]:
        body = {
            "search": {
                "filter": {str(field): {"$eq": str(value)}},
                "cursorPaging": {"limit": 25},
            }
        }
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.post(
                    f"{self._orders_base}/orders/search",
                    headers=self._headers(),
                    json=body,
                )
                resp.raise_for_status()
                payload = resp.json()
                orders = payload.get("orders") or []
                return self._pick_exact_order_match(str(value), orders)
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient search %s=%s failed: %s", field, value, exc)
                return {}

    @staticmethod
    def _normalize_order_number(value: str) -> str:
        text = str(value or "").strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits if digits else text.casefold()

    @classmethod
    def _pick_exact_order_match(cls, requested_number: str, orders: list[Any]) -> dict[str, Any]:
        if not isinstance(orders, list):
            return {}
        requested_norm = cls._normalize_order_number(requested_number)
        if not requested_norm:
            return {}
        for raw in orders:
            if not isinstance(raw, dict):
                continue
            candidate_norm = cls._normalize_order_number(str(raw.get("number") or ""))
            if candidate_norm and candidate_norm == requested_norm:
                return raw
        return {}

    def _cache_scope(self) -> tuple[str, str]:
        try:
            site_id = self._site_id()
            account_id = self._account_id()
        except Exception:  # noqa: BLE001 - cache must never break API access.
            return "", ""
        return str(site_id or "").strip(), str(account_id or "").strip()

    def _cached_order(self, reference: str) -> dict[str, Any] | None:
        cache = getattr(self, "_order_cache", None)
        if cache is None:
            return None
        site_id, account_id = self._cache_scope()
        if not site_id:
            return None
        cached = cache.get_order(site_id=site_id, account_id=account_id, reference=reference)
        if cached is None:
            return None
        logger.debug(
            "Wix order cache hit ref=%s found=%s age_ms=%s",
            str(reference or "").strip(),
            cached.found,
            int(cached.age_seconds * 1000),
        )
        # Negative markers are intentional cache hits.  They avoid repeatedly
        # asking Wix for historical sevDesk references that are known to have
        # no matching Wix order.
        return dict(cached.order) if cached.found else {}

    def _cache_order(self, reference: str, order: dict[str, Any]) -> None:
        cache = getattr(self, "_order_cache", None)
        if cache is None or not order:
            return
        site_id, account_id = self._cache_scope()
        if not site_id:
            return
        cache.put_order(site_id=site_id, account_id=account_id, reference=reference, order=order)

    def _cache_missing_order(self, reference: str) -> None:
        cache = getattr(self, "_order_cache", None)
        if cache is None:
            return
        site_id, account_id = self._cache_scope()
        if not site_id:
            return
        cache.put_missing(site_id=site_id, account_id=account_id, reference=reference)

    def get_cached_order_summary(self, reference: str) -> dict[str, str] | None:
        """Return a normalized order summary from the persistent cache only.

        ``None`` means no cache entry exists.  An empty dict means the
        reference is cached as missing and must not trigger a Wix lookup.
        """
        ref = str(reference or "").strip()
        if not ref:
            return None
        cached = self._cached_order(ref)
        if cached is None:
            return None
        if not cached:
            return {}
        return self._summary_from_order(cached)

    def get_cached_order_line_items(self, reference: str) -> list[WixOrderItem] | None:
        """Return normalized line items from the persistent cache only.

        ``None`` means no cache entry exists.  An empty list can mean either a
        cached missing order or a cached order without line items.
        """
        ref = str(reference or "").strip()
        if not ref:
            return None
        cached = self._cached_order(ref)
        if cached is None:
            return None
        if not cached:
            return []
        if not isinstance(cached.get("lineItems"), list):
            return None
        raw_items = cached.get("lineItems")
        return [_parse_order_line_item(item) for item in raw_items if isinstance(item, dict)]

    def get_cached_reference_digital_only(self, reference: str) -> bool | None:
        """Return cached digital-only classification without calling Wix.

        ``None`` means no usable cache entry exists yet.  Missing orders and
        cached orders without line items also stay unknown because treating them
        as physical would make the Rechnungen overview look complete too early.
        """
        ref = str(reference or "").strip()
        if not ref:
            return None
        cached = self._cached_order(ref)
        if not cached:
            return None
        raw_items = [
            item
            for item in (cached.get("lineItems") if isinstance(cached.get("lineItems"), list) else [])
            if isinstance(item, dict)
        ]
        if not raw_items:
            return None
        return all(self.line_item_is_digital(item) for item in raw_items)

    def get_cached_order_buyer_note(self, reference: str) -> str | None:
        """Return the cached Wix buyer note without calling Wix."""
        ref = str(reference or "").strip()
        if not ref:
            return None
        cached = self._cached_order(ref)
        if not cached:
            return None
        return str(cached.get("buyerNote") or cached.get("buyerNotes") or "").strip()

    def _resolve_order(
        self,
        reference: str,
        *,
        use_cache: bool = True,
        cancel_token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        ref = str(reference or "").strip()
        if not ref or not self.has_credentials():
            return {}
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if use_cache:
            cached = self._cached_order(ref)
            if cached is not None:
                return cached
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if self._looks_like_uuid(ref):
            order_by_id = self._get_order_by_id(ref)
            if order_by_id:
                self._cache_order(ref, order_by_id)
                return order_by_id
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        order = self._search_order_by_field("number", ref)
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if not order:
            order = self._search_order_by_field("orderNumber", ref)
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if not order and not ref.startswith("00"):
            digits = "".join(c for c in ref if c.isdigit())
            if digits and digits != ref:
                order = self._search_order_by_field("number", digits)
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                if not order:
                    order = self._search_order_by_field("orderNumber", digits)
        if order:
            self._cache_order(ref, order)
        elif use_cache:
            self._cache_missing_order(ref)
        return order

    @staticmethod
    def line_item_is_digital(raw: dict[str, Any]) -> bool:
        product_type = str(raw.get("productType") or "").strip().lower()
        if product_type == "digital":
            return True
        item_type = raw.get("itemType") if isinstance(raw.get("itemType"), dict) else {}
        preset = str(item_type.get("preset") or "").strip().lower()
        if preset == "digital":
            return True
        physical_props = raw.get("physicalProperties") if isinstance(raw.get("physicalProperties"), dict) else {}
        shippable_raw = physical_props.get("shippable")
        shippable = str(shippable_raw).strip().lower() if shippable_raw is not None else ""
        if shippable in ("false", "0", "no"):
            return True
        if raw.get("digitalFile"):
            return True
        return False

    def is_reference_digital_only(self, reference: str) -> bool:
        order = self._resolve_order(reference)
        if not order:
            return False
        raw_items = order.get("lineItems") if isinstance(order.get("lineItems"), list) else []
        if not raw_items:
            return False
        return all(self.line_item_is_digital(item) for item in raw_items if isinstance(item, dict))

    def fulfillment_status(self, reference: str) -> str:
        order = self._resolve_order(reference, use_cache=False)
        return str(order.get("fulfillmentStatus") or "").strip().upper() if isinstance(order, dict) else ""

    def _resolve_order_id(self, reference: str) -> str:
        order = self._resolve_order(reference)
        return str(order.get("id") or "").strip()

    def resolve_order(self, reference: str) -> dict[str, Any]:
        """Resolve an order by order number/reference or UUID."""
        return self._resolve_order(reference)

    @staticmethod
    def _norm_text(value: object) -> str:
        return str(value or "").strip()

    @classmethod
    def shipping_address_lines_from_order(cls, order: dict[str, Any]) -> list[str]:
        parts = cls._shipping_address_parts_from_order(order)
        if not parts:
            return []
        name = parts.get("name", "")
        company = parts.get("company", "")
        person_name = parts.get("person_name", "")
        name_lines = [line for line in (company, person_name if person_name != company else "") if line]
        if not name_lines and name:
            name_lines = [name]
        street1 = parts.get("street1", "")
        street2 = parts.get("street2", "")
        postal_code = parts.get("postal_code", "")
        city = parts.get("city", "")
        country = country_label_for_address(parts.get("country", ""))
        city_line = " ".join(part for part in (postal_code, city) if part)

        return [line for line in (*name_lines, street1, street2, city_line, country) if line]

    @classmethod
    def billing_address_lines_from_order(cls, order: dict[str, Any]) -> list[str]:
        parts = cls._billing_address_parts_from_order(order)
        if not parts:
            return []
        name = parts.get("name", "")
        street = parts.get("street1", "")
        street2 = parts.get("street2", "")
        postal_code = parts.get("postal_code", "")
        city = parts.get("city", "")
        country = country_label_for_address(parts.get("country", ""))
        city_line = " ".join(part for part in (postal_code, city) if part)

        return [line for line in (name, street, street2, city_line, country) if line]

    @classmethod
    def best_address_lines_from_order(cls, order: dict[str, Any]) -> list[str]:
        shipping_lines = cls.shipping_address_lines_from_order(order)
        if shipping_lines:
            return shipping_lines
        return cls.billing_address_lines_from_order(order)

    def resolve_order_address_lines(self, reference: str) -> list[str]:
        order = self._resolve_order(reference)
        if not order:
            return []
        return self.best_address_lines_from_order(order)

    @classmethod
    def _summary_from_order(cls, order: dict[str, Any]) -> dict[str, str]:
        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
        first = cls._norm_text(buyer.get("firstName"))
        last = cls._norm_text(buyer.get("lastName"))
        full_name = " ".join(part for part in (first, last) if part).strip()
        email = cls._norm_text(buyer.get("email"))

        shipping_lines = cls.best_address_lines_from_order(order)
        shipping_parts = cls._shipping_address_parts_from_order(order)
        billing_lines = cls.billing_address_lines_from_order(order)
        billing_parts = cls._billing_address_parts_from_order(order)
        if not full_name:
            full_name = shipping_parts.get("name", "")

        return {
            "wix_order_id": cls._norm_text(order.get("id")),
            "wix_order_number": cls._norm_text(order.get("number")),
            "wix_customer_name": full_name,
            "wix_customer_email": email,
            "wix_shipping_street": shipping_parts.get("street1", ""),
            "wix_shipping_street2": shipping_parts.get("street2", ""),
            "wix_shipping_zip": shipping_parts.get("postal_code", ""),
            "wix_shipping_city": shipping_parts.get("city", ""),
            "wix_shipping_country": shipping_parts.get("country", ""),
            "wix_shipping_address": "\n".join(shipping_lines),
            "wix_billing_street": billing_parts.get("street1", ""),
            "wix_billing_street2": billing_parts.get("street2", ""),
            "wix_billing_zip": billing_parts.get("postal_code", ""),
            "wix_billing_city": billing_parts.get("city", ""),
            "wix_billing_country": billing_parts.get("country", ""),
            "wix_billing_address": "\n".join(billing_lines),
        }

    def resolve_order_summary(
        self,
        reference: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> dict[str, str]:
        """Return normalized customer/order fields used by the details panel."""
        started = time.perf_counter()
        order = self._resolve_order(reference, cancel_token=cancel_token)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.debug(
            "Wix metric summary_ms=%s ref=%s found=%s",
            elapsed_ms,
            str(reference or "").strip(),
            bool(order),
        )
        if not order:
            return {}
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        return self._summary_from_order(order)

    def resolve_plc_shipping_context(self, reference: str) -> dict[str, str]:
        """Return normalized address contact fields needed by the PLC dialog.

        The regular invoice detail summary intentionally stays compact. PLC
        customs validation additionally needs recipient email/phone, so this
        method exposes them only in the short-lived dialog context.
        """
        order = self._resolve_order(reference)
        if not order:
            return {}
        parts = self._shipping_address_parts_from_order(order)
        shipping = order.get("shippingInfo") if isinstance(order.get("shippingInfo"), dict) else {}
        destination = shipping.get("shippingDestination") if isinstance(shipping.get("shippingDestination"), dict) else {}
        contact = destination.get("contactDetails") if isinstance(destination.get("contactDetails"), dict) else {}
        shipment_details = shipping.get("shipmentDetails") if isinstance(shipping.get("shipmentDetails"), dict) else {}
        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}

        email = self._address_field(
            contact,
            shipment_details,
            buyer,
            shipping,
            keys=("email", "emailAddress"),
        )
        phone = self._address_field(
            contact,
            shipment_details,
            buyer,
            shipping,
            keys=("phone", "phoneNumber", "phoneNumber1", "mobile", "mobilePhone"),
        )
        return {
            **parts,
            "email": email,
            "phone": phone,
            "order_number": self._norm_text(order.get("number")),
        }

    def resolve_order_dashboard_url(self, reference: str) -> str:
        """Return Wix dashboard URL for an order reference (number or UUID)."""
        ref = str(reference or "").strip()
        order: dict[str, Any] = {}
        # Wix search can be briefly stale on first lookup; retry once/twice before failing.
        for attempt in range(3):
            order = self._resolve_order(ref)
            if order:
                break
            if attempt < 2:
                time.sleep(0.25)
        order_id = str(order.get("id") or "").strip()
        site_id = self._site_id().strip()
        if not order_id or not site_id:
            logger.debug("Wix dashboard resolve failed ref=%s attempts=%s", ref, 3)
            return ""
        return f"https://manage.wix.com/dashboard/{site_id}/ecom-platform/order-details/{order_id}"

    def list_fulfillments(self, reference: str) -> list[dict[str, Any]]:
        order_id = self._resolve_order_id(reference)
        if not order_id or not self.has_credentials():
            return []
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.get(
                    f"{self._orders_base}/fulfillments/orders/{order_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict):
                    data = payload.get("fulfillments")
                    if isinstance(data, list):
                        return [item for item in data if isinstance(item, dict)]
                if isinstance(payload, list):
                    return [item for item in payload if isinstance(item, dict)]
                return []
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient list fulfillments failed: %s", exc)
                return []

    def fetch_order_payment_details(self, order_id: str) -> dict[str, Any]:
        real_id = str(order_id or "").strip()
        if not real_id or not self.has_credentials():
            return {}
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.get(
                    f"{self._orders_base}/payments/orders/{real_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                payload = resp.json() if resp.content else {}
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient payment details order_id=%s failed: %s", real_id, exc)
                return {}
        if not isinstance(payload, dict):
            return {}
        order_transactions = payload.get("orderTransactions")
        if isinstance(order_transactions, list):
            source = next((item for item in order_transactions if isinstance(item, dict)), {})
        elif isinstance(order_transactions, dict):
            source = order_transactions
        else:
            source = payload
        if not isinstance(source, dict):
            return {}

        provider_ids: list[str] = []
        primary_provider_id = ""
        provider_hint = ""
        payment_status = ""
        payment_created = ""
        payment_updated = ""
        amount = ""
        for key in ("paymentProviderTransactionId", "paymentGatewayTransactionId", "externalTransactionId"):
            candidate = str(source.get(key) or payload.get(key) or "").strip()
            if candidate:
                provider_ids.append(candidate)
                if not primary_provider_id:
                    primary_provider_id = candidate
        if not provider_hint:
            provider_hint = str(source.get("provider") or payload.get("provider") or "").strip()
        if not payment_status:
            payment_status = str(source.get("paymentStatus") or payload.get("paymentStatus") or "").strip()
        if not payment_created:
            payment_created = str(source.get("paymentCreatedDate") or payload.get("paymentCreatedDate") or "").strip()
        if not payment_updated:
            payment_updated = str(source.get("paymentUpdatedDate") or payload.get("paymentUpdatedDate") or "").strip()
        if not amount:
            amount = str(source.get("amount") or payload.get("amount") or "").strip()
        payments = source.get("payments")
        for payment in payments if isinstance(payments, list) else []:
            if not isinstance(payment, dict):
                continue
            regular = payment.get("regularPaymentDetails") if isinstance(payment.get("regularPaymentDetails"), dict) else {}
            for key in ("providerTransactionId", "gatewayTransactionId", "paymentOrderId"):
                candidate = str(regular.get(key) or payment.get(key) or "").strip()
                if candidate:
                    provider_ids.append(candidate)
                    if not primary_provider_id:
                        primary_provider_id = candidate
            if not provider_hint:
                provider_hint = str(payment.get("provider") or regular.get("provider") or source.get("provider") or "").strip()
            if not payment_status:
                payment_status = str(payment.get("status") or source.get("paymentStatus") or "").strip()
            if not payment_created:
                payment_created = str(payment.get("createdDate") or payment.get("createdAt") or "").strip()
            if not payment_updated:
                payment_updated = str(payment.get("updatedDate") or payment.get("updatedAt") or "").strip()
            amount_obj = payment.get("amount") if isinstance(payment.get("amount"), dict) else {}
            if not amount:
                amount = str(amount_obj.get("amount") or amount_obj.get("value") or source.get("amount") or "").strip()

        unique_provider_ids: list[str] = []
        for candidate in provider_ids:
            if candidate and candidate not in unique_provider_ids:
                unique_provider_ids.append(candidate)
        if not primary_provider_id and unique_provider_ids:
            primary_provider_id = unique_provider_ids[0]
        return {
            "paymentStatus": payment_status or str(source.get("paymentStatus") or "").strip(),
            "provider": provider_hint,
            "providerTransactionId": primary_provider_id,
            "providerTransactionIds": unique_provider_ids,
            "paymentCreatedDate": payment_created,
            "paymentUpdatedDate": payment_updated,
            "amount": amount,
        }

    def get_fulfillable_items(self, reference: str) -> list[dict[str, Any]]:
        started = time.perf_counter()
        order_id = self._resolve_order_id(reference)
        if not order_id or not self.has_credentials():
            return []
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.get(
                    f"{self._orders_base}/fulfillments/orders/{order_id}/fulfillable-items",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict):
                    data = payload.get("fulfillableLineItems")
                    if isinstance(data, list):
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        logger.debug(
                            "Wix metric fulfillable_items_ms=%s ref=%s items=%s",
                            elapsed_ms,
                            str(reference or "").strip(),
                            len(data),
                        )
                        return [item for item in data if isinstance(item, dict)]
                if isinstance(payload, list):
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    logger.debug(
                        "Wix metric fulfillable_items_ms=%s ref=%s items=%s",
                        elapsed_ms,
                        str(reference or "").strip(),
                        len(payload),
                    )
                    return [item for item in payload if isinstance(item, dict)]
                return []
            except httpx.HTTPError as exc:
                response = getattr(exc, "response", None)
                if getattr(response, "status_code", None) == 404:
                    logger.debug(
                        "WixOrdersClient fulfillable items unavailable ref=%s status=404",
                        str(reference or "").strip(),
                    )
                else:
                    logger.warning("WixOrdersClient get fulfillable items failed: %s", exc)
                return []

    def physical_fulfillment_line_items(self, reference: str) -> list[dict[str, object]]:
        order = self._resolve_order(reference)
        return self._physical_fulfillment_line_items_from_order(order)

    @classmethod
    def _physical_fulfillment_line_items_from_order(cls, order: dict[str, Any]) -> list[dict[str, object]]:
        raw_items = order.get("lineItems") if isinstance(order.get("lineItems"), list) else []
        items: list[dict[str, object]] = []
        for raw in raw_items:
            if not isinstance(raw, dict) or cls.line_item_is_digital(raw):
                continue
            item_id = str(raw.get("id") or raw.get("lineItemId") or "").strip()
            if not item_id:
                continue
            quantity_raw = raw.get("quantity") or raw.get("qty") or 1
            try:
                quantity = int(float(str(quantity_raw)))
            except (TypeError, ValueError):
                quantity = 1
            if quantity <= 0:
                continue
            items.append({"id": item_id, "quantity": quantity})
        return items

    def create_fulfillment(
        self,
        reference: str,
        line_items: list[dict[str, Any]],
        *,
        notify_customer: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        order_id = self._resolve_order_id(reference)
        items = [item for item in line_items if isinstance(item, dict)]
        if not order_id or not items or not self.has_credentials():
            return {}
        payload: dict[str, Any] = {
            "fulfillment": {
                "lineItems": items,
            },
            "notifyCustomer": bool(notify_customer),
        }
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.post(
                    f"{self._orders_base}/fulfillments/orders/{order_id}/create-fulfillment",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                logger.debug(
                    "Wix metric create_fulfillment_ms=%s ref=%s lines=%s",
                    elapsed_ms,
                    str(reference or "").strip(),
                    len(items),
                )
                return resp.json() if resp.content else {"created": True}
            except httpx.HTTPError as exc:
                response = getattr(exc, "response", None)
                if getattr(response, "status_code", None) == 409:
                    logger.info("WixOrdersClient create fulfillment already exists ref=%s", reference)
                    return {"already_exists": True}
                logger.warning("WixOrdersClient create fulfillment failed: %s", exc)
                return {}

    def get_order_refundability(self, order_id: str) -> dict[str, Any]:
        real_id = str(order_id or "").strip()
        if not real_id or not self.has_credentials():
            return {}
        body = {"orderId": real_id}
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.post(
                    f"{self._orders_base}/order-billing/get-order-refundability",
                    headers=self._headers(),
                    json=body,
                )
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except httpx.HTTPError as exc:
                logger.warning(
                    "WixOrdersClient refundability order_id=%s failed: %s",
                    real_id,
                    exc,
                )
                return {}

    def refund_order_payments(
        self,
        order_id: str,
        payment_refunds: list[dict[str, Any]],
        *,
        send_customer_email: bool = True,
        customer_reason: str = "",
    ) -> dict[str, Any]:
        real_id = str(order_id or "").strip()
        refunds = [entry for entry in payment_refunds if isinstance(entry, dict)]
        if not real_id or not refunds or not self.has_credentials():
            return {}

        body: dict[str, Any] = {
            "orderId": real_id,
            "paymentRefunds": refunds,
            "sideEffects": {
                "notifications": {
                    "sendCustomerEmail": bool(send_customer_email),
                },
            },
        }
        if customer_reason.strip():
            body["customerReason"] = customer_reason.strip()

        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.post(
                    f"{self._orders_base}/order-billing/refund-payments",
                    headers=self._headers(),
                    json=body,
                )
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient refund payments order_id=%s failed: %s", real_id, exc)
                return {}

    def refund_full_order(
        self,
        reference: str,
        *,
        send_customer_email: bool = True,
        customer_reason: str = "",
    ) -> dict[str, Any]:
        """Refund all currently refundable payments for an order reference."""
        order = self._resolve_order(reference)
        order_id = str(order.get("id") or "").strip()
        if not order_id:
            return {}

        refundability = self.get_order_refundability(order_id)
        payments = refundability.get("payments")
        if not isinstance(payments, list):
            payments = []

        payment_refunds: list[dict[str, Any]] = []
        for entry in payments:
            if not isinstance(entry, dict) or not entry.get("refundable"):
                continue
            payment = entry.get("payment")
            if not isinstance(payment, dict):
                continue
            payment_id = str(payment.get("paymentId") or "").strip()
            amount_obj = entry.get("availableRefundAmount")
            if not isinstance(amount_obj, dict):
                continue
            amount = str(amount_obj.get("amount") or "").strip()
            if not payment_id or not amount:
                continue
            payment_refunds.append(
                {
                    "paymentId": payment_id,
                    "amount": {"amount": amount},
                }
            )

        if not payment_refunds:
            return {}

        return self.refund_order_payments(
            order_id,
            payment_refunds,
            send_customer_email=send_customer_email,
            customer_reason=customer_reason,
        )

    @staticmethod
    def _looks_like_uuid(value: str) -> bool:
        parts = value.split("-")
        return len(parts) == 5 and len(value) == 36

    def fetch_order_line_items(
        self,
        reference: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> list[WixOrderItem]:
        """Resolve a sevDesk order reference to Wix line items.

        *reference* can be a Wix order number (digits) or order UUID.
        Returns an empty list when credentials are missing or order not found.
        """
        started = time.perf_counter()
        ref = str(reference or "").strip()
        if not ref or not self.has_credentials():
            return []

        order = self._resolve_order(ref, cancel_token=cancel_token)
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if order and not isinstance(order.get("lineItems"), list):
            order = self._resolve_order(ref, use_cache=False, cancel_token=cancel_token)
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

        if not order:
            logger.debug("WixOrdersClient: no order found for reference=%r", ref)
            return []

        raw_items = order.get("lineItems") or []
        items: list[WixOrderItem] = []
        for item in raw_items:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            if isinstance(item, dict):
                items.append(_parse_order_line_item(item))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.debug(
            "Wix metric line_items_ms=%s ref=%s items=%s",
            elapsed_ms,
            ref,
            len(items),
        )
        return items
