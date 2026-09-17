"""Deterministic conflict classification and queue priority."""

from __future__ import annotations

_CLASSIFICATION: dict[str, tuple[str, str, int]] = {
    "sku": ("DUPLICATE_SKU", "CRITICAL", 100),
    "asin": ("ASIN_CONFLICT", "CRITICAL", 100),
    "fnsku": ("FNSKU_CONFLICT", "CRITICAL", 100),
    "isbn": ("IDENTIFIER_COLLISION", "CRITICAL", 100),
    "mapping": ("WRONG_PRODUCT_MAPPING", "CRITICAL", 100),
    "price": ("PRICE_DRIFT", "HIGH", 60),
    "tax": ("VAT_DRIFT", "HIGH", 60),
    "vat": ("VAT_DRIFT", "HIGH", 60),
    "stock": ("STOCK_DRIFT", "HIGH", 60),
    "active": ("ACTIVE_STATUS_DRIFT", "HIGH", 60),
    "visible": ("ACTIVE_STATUS_DRIFT", "HIGH", 60),
    "name": ("TITLE_DRIFT", "MEDIUM", 35),
    "title": ("TITLE_DRIFT", "MEDIUM", 35),
    "brand": ("BRAND_DRIFT", "MEDIUM", 35),
    "category": ("CATEGORY_DRIFT", "MEDIUM", 35),
    "description": ("DESCRIPTION_DRIFT", "LOW", 15),
    "bullet": ("BULLET_DRIFT", "LOW", 15),
    "tag": ("TAG_DRIFT", "LOW", 15),
}


def classify(field_path: str, channel: str) -> tuple[str, str, int]:
    field = field_path.casefold()
    for needle, result in _CLASSIFICATION.items():
        if needle in field:
            conflict_type, severity, score = result
            return conflict_type, severity, score + (30 if channel == "wix" else 0)
    return "POSSIBLE_DUPLICATE_PRODUCT", "MEDIUM", 30
