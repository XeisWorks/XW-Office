"""ProductCatalogService — canonical product registry with SKU resolution.

Source of truth for product metadata, print rules, and file paths.
All writes to sevDesk Part stock go through PartClient (separate concern).
"""
from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from xw_studio.core.shared_paths import resolve_shared_path

if TYPE_CHECKING:
    from xw_studio.repositories.settings_kv import SettingKvRepository
    from xw_studio.services.sevdesk.part_client import SevdeskPart

logger = logging.getLogger(__name__)


def _normalize_musikheroes_tokens(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    normalized = value

    normalized = re.sub(r"\bchristkindl[\s\-]*hits?\b", " ckh ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\btanzl\s*(?:&|und)\s*g['`]?\s*stanzl\b", " tg ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bt\s*&\s*g\b", " tg ", normalized, flags=re.IGNORECASE)

    normalized = re.sub(r"\blead\s*sheet\b", " ls ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bleadsheet\b", " ls ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bbegl(?:eit(?:stimme)?)?\.?\s*c?\b", " ls ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b2\s*\.?\s*st(?:imme)?\s*\.?\s*b\b", " 2b ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b2\s*\.?\s*st(?:imme)?\s*\.?\s*c\b", " 2c ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b2\s*\.?\s*st(?:imme)?\s*\.?\s*f\b", " 2f ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b2b[\s\-_]*(?:hoch|h)\b", " 2bh ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b2b[\s\-_]*(?:tief|t)\b", " 2bt ", normalized, flags=re.IGNORECASE)
    return normalized


def normalize_legacy_title(value: str) -> str:
    """Return the same title key shape used by the legacy inventory mapper."""
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = _normalize_musikheroes_tokens(normalized)
    normalized = normalized.replace("&", " und ")
    normalized = re.sub(r"[^a-z0-9#]+", " ", normalized)
    normalized = normalized.replace("#", " ")
    return " ".join(normalized.split())


@dataclass
class PrintRule:
    """Per-product print configuration."""

    min_stock_target: int = 5
    """If on-hand stock falls at or below this, trigger a reprint."""

    reprint_batch_qty: int = 3
    """How many copies to print per reprint run."""


@dataclass
class Product:
    """Canonical product entity resolved from the pipeline DB."""

    id: str  # UUID string
    sku: str
    name: str
    category: str = ""
    brand_name: str = ""
    brand_id: str = ""
    is_digital: bool = False
    sevdesk_part_id: str = ""
    wix_product_id: str = ""
    print_file_path: str = ""
    print_rule: PrintRule = field(default_factory=PrintRule)
    status: str = "draft"  # draft / review / live

    @property
    def print_path(self) -> Path | None:
        """Return Path if print_file_path is non-empty, else None."""
        p = self.print_file_path.strip()
        return Path(p) if p else None


@dataclass
class StockStatus:
    """Stock snapshot for a single product (read from sevDesk or cache)."""

    sku: str
    product_name: str
    is_digital: bool
    on_hand: int
    min_stock_target: int
    reprint_batch_qty: int

    @property
    def is_unlimited(self) -> bool:
        return self.is_digital

    @property
    def needs_reprint(self) -> bool:
        """True when physical stock is at or below the target threshold."""
        return not self.is_digital and self.on_hand <= self.min_stock_target

    @property
    def display_stock(self) -> str:
        if self.is_digital:
            return "∞"
        return str(self.on_hand)

    @property
    def status_label(self) -> str:
        if self.is_digital:
            return "Digital"
        if self.on_hand == 0:
            return f"Leer — muss gedruckt werden ({self.reprint_batch_qty} Stk)"
        if self.needs_reprint:
            return (
                f"Niedrig ({self.on_hand} Stk) — "
                f"Nachdruck empfohlen ({self.reprint_batch_qty} Stk)"
            )
        return f"Im Lager ({self.on_hand} Stk)"


class ProductCatalogService:
    """Central registry for canonical product metadata.

    In Phase A/B this operates as an in-memory + sevDesk-backed service.
    Once DB migration 002 is applied and a database session is available,
    the implementation can be swapped to use the `product` table directly.
    The interface stays stable.
    """

    def __init__(self, settings_repo: "SettingKvRepository | None" = None) -> None:
        self._settings_repo = settings_repo
        # In-memory cache: canonical SKU -> Product
        self._by_sku: dict[str, Product] = {}
        # Alias map: any_sku -> canonical_sku
        self._alias_map: dict[str, str] = {}
        self._direct_print_config: dict[str, dict[str, object]] = {}
        self.reload_from_settings()

    # ------------------------------------------------------------------ #
    # Upsert from external sources                                         #
    # ------------------------------------------------------------------ #

    def upsert_from_sevdesk(self, part: SevdeskPart) -> Product:
        """Register or update a product from a sevDesk Part object."""
        canonical_sku = part.sku.strip().upper()
        if not canonical_sku:
            canonical_sku = f"SEVDESK-{part.id}"

        existing = self._by_sku.get(canonical_sku)
        if existing is not None:
            # Update mutable fields
            existing.sevdesk_part_id = part.id
            existing.name = part.name or existing.name
            existing.is_digital = not part.stock_enabled
            return existing

        product = Product(
            id=str(uuid.uuid4()),
            sku=canonical_sku,
            name=part.name,
            sevdesk_part_id=part.id,
            is_digital=not part.stock_enabled,
            print_rule=PrintRule(),
        )
        self._by_sku[canonical_sku] = product
        logger.debug("Registered product %s from sevDesk Part %s", canonical_sku, part.id)
        return product

    # ------------------------------------------------------------------ #
    # SKU resolution                                                       #
    # ------------------------------------------------------------------ #

    def resolve_sku(self, raw_sku: str) -> Product | None:
        """Return Product for raw_sku including alias lookup."""
        sku = raw_sku.strip().upper()
        product = self._by_sku.get(sku)
        if product is not None:
            return product
        canonical = self._alias_map.get(sku)
        if canonical is not None:
            return self._by_sku.get(canonical)
        return None

    def resolve_print_config(self, raw_sku: str, *, title: str = "") -> dict[str, object]:
        sku = raw_sku.strip().upper()
        if not sku:
            return {}
        config = self._direct_print_config.get(sku) or {}
        if not isinstance(config, dict):
            return {}
        titles = config.get("titles") if isinstance(config.get("titles"), dict) else {}
        title_key = str(title or "").strip()
        if title_key and title_key in titles and isinstance(titles[title_key], dict):
            return dict(titles[title_key])
        normalized_title_key = normalize_legacy_title(title_key)
        if normalized_title_key:
            for candidate_title, candidate_config in titles.items():
                if not isinstance(candidate_config, dict):
                    continue
                if normalize_legacy_title(str(candidate_title or "")) == normalized_title_key:
                    return dict(candidate_config)
        default = config.get("default")
        return dict(default) if isinstance(default, dict) else {}

    def register_alias(self, alias_sku: str, canonical_sku: str) -> None:
        alias = alias_sku.strip().upper()
        canonical = canonical_sku.strip().upper()
        if canonical not in self._by_sku:
            raise KeyError(f"Canonical SKU {canonical!r} not found in catalog")
        self._alias_map[alias] = canonical
        logger.debug("Alias %s -> %s registered", alias, canonical)

    # ------------------------------------------------------------------ #
    # Print rule management                                                #
    # ------------------------------------------------------------------ #

    def set_print_rule(
        self,
        sku: str,
        *,
        min_stock_target: int,
        reprint_batch_qty: int,
    ) -> None:
        product = self.resolve_sku(sku)
        if product is None:
            raise KeyError(f"Product {sku!r} not found")
        product.print_rule = PrintRule(
            min_stock_target=min_stock_target,
            reprint_batch_qty=reprint_batch_qty,
        )

    def set_print_file_path(self, sku: str, path: str) -> None:
        product = self.resolve_sku(sku)
        if product is None:
            raise KeyError(f"Product {sku!r} not found")
        product.print_file_path = path

    def reload_from_settings(self) -> None:
        if self._settings_repo is None:
            return
        raw = self._settings_repo.get_value_json("inventory.products")
        if not raw:
            return
        try:
            import json

            data = json.loads(raw)
        except Exception:
            return
        if not isinstance(data, list):
            return

        self._by_sku.clear()
        self._alias_map.clear()
        self._direct_print_config.clear()
        for item in data:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku") or "").strip().upper()
            if not sku:
                continue
            product = Product(
                id=f"settings::{sku}",
                sku=sku,
                name=str(item.get("name") or sku),
                category=str(item.get("category") or ""),
                brand_name=str(item.get("brand_name") or item.get("brand") or ""),
                brand_id=str(item.get("brand_id") or ""),
                sevdesk_part_id=str(item.get("sevdesk_id") or ""),
                wix_product_id=str(item.get("wix_id") or ""),
                print_file_path=resolve_shared_path(
                    str(item.get("print_file_path") or "")
                ),
            )
            self._by_sku[sku] = product
            titles: dict[str, dict[str, object]] = {}
            raw_titles = item.get("title_print_configs")
            if isinstance(raw_titles, dict):
                for raw_title, raw_cfg in raw_titles.items():
                    if not isinstance(raw_cfg, dict):
                        continue
                    title = str(raw_title or "").strip()
                    if not title:
                        continue
                    titles[title] = {
                        "path": resolve_shared_path(
                            str(raw_cfg.get("path") or "")
                        ),
                        "profile_id": str(raw_cfg.get("profile_id") or "").strip(),
                        "print_plan": [
                            entry for entry in (raw_cfg.get("print_plan") or [])
                            if isinstance(entry, dict)
                        ],
                    }
            self._direct_print_config[sku] = {
                "default": {
                    "path": resolve_shared_path(
                        str(item.get("print_file_path") or "")
                    ),
                    "profile_id": str(item.get("print_profile_id") or "").strip(),
                    "print_plan": [
                        entry for entry in (item.get("print_plan") or [])
                        if isinstance(entry, dict)
                    ],
                },
                "titles": titles,
            }

    # ------------------------------------------------------------------ #
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    def list_all(self) -> list[Product]:
        return list(self._by_sku.values())

    def get_by_sku(self, sku: str) -> Product | None:
        return self.resolve_sku(sku)
