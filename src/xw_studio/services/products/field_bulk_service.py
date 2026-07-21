"""Product field bulk-edit service for targeted field updates.

Centralizes preview + apply logic for generic field changes (price, weight, categories, etc.)
Supports local DB + optional Wix writeback, with field-specific handling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Any

from xw_studio.services.inventory.service import InventoryService, ProductRow
from xw_studio.services.wix.client import WixProduct
from xw_studio.services.wix.product_details_client import WixProductDetailsClient

logger = logging.getLogger(__name__)


class FieldOperatorType(str, Enum):
    """Operator types for field modifications."""

    SET = "set"  # Set field to exact value
    ADD_PERCENT = "add_percent"  # Add percentage to numeric field
    SUBTRACT_PERCENT = "subtract_percent"  # Subtract percentage from numeric field


@dataclass(frozen=True)
class FieldDefinition:
    """Defines a product field: name, UI label, data type, writable status."""

    field_name: str  # Internal name (price_eur, on_hand, brand_name, etc.)
    label: str  # UI display label (German)
    field_type: str  # "text", "number", "decimal", "multi_select"
    writable_local: bool = True  # Can be written to local DB?
    writable_wix: bool = False  # Can be synced to Wix?
    wix_property: str = ""  # Wix API property name (if different)


# Standard fields available for bulk edit
BULK_EDITABLE_FIELDS = {
    "price_eur": FieldDefinition(
        field_name="price_eur",
        label="Preis",
        field_type="decimal",
        writable_local=True,
        writable_wix=True,
        wix_property="price",
    ),
    "on_hand": FieldDefinition(
        field_name="on_hand",
        label="Bestand",
        field_type="number",
        writable_local=True,
        writable_wix=True,
        wix_property="inventory_quantity",
    ),
    "brand_name": FieldDefinition(
        field_name="brand_name",
        label="Marke",
        field_type="text",
        writable_local=True,
        writable_wix=True,
        wix_property="brand",
    ),
    "category": FieldDefinition(
        field_name="category",
        label="Kategorie",
        field_type="text",
        writable_local=True,
        writable_wix=False,  # Requires category ID resolution
    ),
    "name": FieldDefinition(
        field_name="name",
        label="Produktname",
        field_type="text",
        writable_local=True,
        writable_wix=True,
        wix_property="name",
    ),
    "visible": FieldDefinition(
        field_name="visible",
        label="Sichtbar",
        field_type="text",
        writable_local=False,
        writable_wix=True,
        wix_property="visible",
    ),
    "compare_at_price": FieldDefinition(
        field_name="compare_at_price",
        label="Sale-Preis / Compare-at",
        field_type="decimal",
        writable_local=False,
        writable_wix=True,
        wix_property="compareAtPrice",
    ),
    "cost": FieldDefinition(
        field_name="cost",
        label="Herstellungskosten",
        field_type="decimal",
        writable_local=False,
        writable_wix=True,
        wix_property="cost",
    ),
    "weight": FieldDefinition(
        field_name="weight",
        label="Versandgewicht",
        field_type="decimal",
        writable_local=False,
        writable_wix=True,
        wix_property="weight",
    ),
    "description": FieldDefinition(
        field_name="description",
        label="Infoabschnitt / Beschreibung",
        field_type="text",
        writable_local=False,
        writable_wix=True,
        wix_property="description",
    ),
    "categories": FieldDefinition(
        field_name="categories",
        label="Kategorien (CSV)",
        field_type="text",
        writable_local=False,
        writable_wix=True,
        wix_property="categories",
    ),
    "ribbon": FieldDefinition(
        field_name="ribbon",
        label="Banner / Ribbon",
        field_type="text",
        writable_local=False,
        writable_wix=True,
        wix_property="ribbon",
    ),
}


@dataclass(frozen=True)
class FieldUpdateItem:
    """Result for one SKU in a field update run."""

    sku: str
    product_name: str
    field_name: str
    old_value: str
    new_value: str
    status: str  # "would-change", "skipped", "changed", "failed"
    message: str = ""


@dataclass(frozen=True)
class FieldBulkUpdateReport:
    """Aggregated dry-run/apply report for field updates."""

    requested: int
    changed: int
    skipped: int
    failed: int
    dry_run: bool
    field_name: str
    operator: str  # FieldOperatorType value
    value: str
    wix_attempted: int = 0
    wix_updated: int = 0
    wix_failed: int = 0
    items: list[FieldUpdateItem] = field(default_factory=list)


class ProductFieldBulkService:
    """Service for bulk edits across all editable product fields."""

    def __init__(self, inventory: InventoryService, wix_client: WixProductDetailsClient) -> None:
        self._inventory = inventory
        self._wix_client = wix_client

    def list_products(self) -> list[ProductRow]:
        """Return all local product rows from the inventory store."""
        return self._inventory.list_products()

    def get_editable_fields(self) -> dict[str, FieldDefinition]:
        """Return all available bulk-editable field definitions."""
        return dict(BULK_EDITABLE_FIELDS)

    def preview_field_update(
        self,
        skus: list[str],
        field_name: str,
        operator: FieldOperatorType | str,
        value: str,
        *,
        wix_products: list[WixProduct] | None = None,
    ) -> FieldBulkUpdateReport:
        """Preview field update without persisting changes."""
        local_products = self._inventory.list_products()
        return self._build_report(
            skus=skus,
            field_name=field_name,
            operator=str(operator),
            value=value,
            dry_run=True,
            wix_products=wix_products,
            local_products=local_products,
        )

    def apply_field_update(
        self,
        skus: list[str],
        field_name: str,
        operator: FieldOperatorType | str,
        value: str,
        *,
        sync_wix: bool = False,
        wix_products: list[WixProduct] | None = None,
    ) -> FieldBulkUpdateReport:
        """Apply field update locally and optionally write to Wix."""
        local_products = self._inventory.list_products()
        report = self._build_report(
            skus=skus,
            field_name=field_name,
            operator=str(operator),
            value=value,
            dry_run=False,
            wix_products=wix_products,
            local_products=local_products,
        )
        field_def = BULK_EDITABLE_FIELDS.get(field_name)
        if field_def is None:
            raise ValueError(f"Unknown field: {field_name}")

        if report.changed <= 0:
            return report

        local_skus = {row.sku.strip().upper() for row in local_products}
        if (not sync_wix) and (
            (not field_def.writable_local)
            or any(
                item.status == "changed" and item.sku.strip().upper() not in local_skus
                for item in report.items
            )
        ):
            raise ValueError("Diese Auswahl erfordert Wix Writeback.")

        if field_def.writable_local:
            self._persist_local_changes(
                report,
                field_name,
                operator=str(operator),
                value=value,
                local_products=local_products,
            )

        if sync_wix and field_def.writable_wix:
            # Reflect locally changed values without another database round-trip.
            effective_products = self._updated_local_rows(
                local_products,
                report,
                field_name,
                operator=str(operator),
                value=value,
            ) if field_def.writable_local else local_products
            return self._apply_wix_field_update(
                report,
                wix_products=wix_products,
                local_products=effective_products,
            )
        return report

    def _persist_local_changes(
        self,
        report: FieldBulkUpdateReport,
        field_name: str,
        *,
        operator: str,
        value: str,
        local_products: list[ProductRow],
    ) -> None:
        """Persist locally writable field changes to the inventory store."""
        selected = {item.sku.strip().upper() for item in report.items if item.status == "changed"}
        if not selected:
            return

        updated_rows = self._updated_local_rows(
            local_products,
            report,
            field_name,
            operator=operator,
            value=value,
        )
        updates: dict[str, dict[str, object]] = {}
        for row in updated_rows:
            sku = row.sku.strip().upper()
            if sku not in selected:
                continue
            updates[sku] = {field_name: self._get_field_value(row, field_name)}
        atomic_update = getattr(self._inventory, "update_product_fields", None)
        if callable(atomic_update):
            atomic_update(updates)
        else:
            self._inventory.save_products(updated_rows)

    def _updated_local_rows(
        self,
        local_products: list[ProductRow],
        report: FieldBulkUpdateReport,
        field_name: str,
        *,
        operator: str,
        value: str,
    ) -> list[ProductRow]:
        selected = {item.sku.strip().upper() for item in report.items if item.status == "changed"}
        updated_rows: list[ProductRow] = []
        for row in local_products:
            sku = row.sku.strip().upper()
            if sku not in selected:
                updated_rows.append(row)
                continue

            old_val = self._get_field_value(row, field_name)
            new_val = self._compute_new_value(old_val, operator, value, field_name)
            updated_row = self._set_field_on_row(row, field_name, new_val)
            updated_rows.append(updated_row)

        return updated_rows

    def _apply_wix_field_update(
        self,
        local_report: FieldBulkUpdateReport,
        *,
        wix_products: list[WixProduct] | None = None,
        local_products: list[ProductRow],
    ) -> FieldBulkUpdateReport:
        """Write field updates to Wix via WixProductDetailsClient (version-aware)."""
        if not self._wix_client.has_credentials():
            return local_report

        field_def = BULK_EDITABLE_FIELDS.get(local_report.field_name)
        if not field_def or not field_def.writable_wix:
            return local_report

        wix_attempted = 0
        wix_updated = 0
        wix_failed = 0
        wix_by_sku = {
            row.sku.strip().upper(): row
            for row in (wix_products or [])
            if row.sku.strip()
        }
        local_by_sku = {
            row.sku.strip().upper(): row
            for row in local_products
            if row.sku.strip()
        }

        # Collect (product_id, new_value) pairs for changed items
        bulk_ids: list[str] = []
        value_by_pid: dict[str, str] = {}

        for item in local_report.items:
            if item.status != "changed":
                continue

            sku = item.sku.strip().upper()
            product = local_by_sku.get(sku)
            wix_product = wix_by_sku.get(sku)
            product_id = (
                (product.wix_id if product is not None else "")
                or (wix_product.id if wix_product is not None else "")
            ).strip()
            if not product_id:
                wix_failed += 1
                continue
            bulk_ids.append(product_id)
            value_by_pid[product_id] = item.new_value

        if not bulk_ids:
            pass  # nothing to push
        elif len(bulk_ids) == 1:
            # Single product — use the field-specific method for best semantics
            pid = bulk_ids[0]
            val = value_by_pid[pid]
            wix_attempted += 1
            result = self._call_details_update(pid, field_def.wix_property or field_def.field_name, val)
            if result.succeeded:
                wix_updated += 1
            else:
                wix_failed += 1
                if result.errors:
                    logger.warning("Wix field update failed for %s: %s", pid, result.errors[0])
        else:
            # Multiple products — use bulk_update_property when all values are equal,
            # otherwise fall back to per-product calls.
            unique_values = set(value_by_pid.values())
            wix_attempted += len(bulk_ids)
            if len(unique_values) == 1:
                single_val = next(iter(unique_values))
                coerced = self._coerce_for_details(field_def.wix_property or field_def.field_name, single_val)
                bulk_result = self._wix_client.bulk_update_property(
                    bulk_ids,
                    field=field_def.wix_property or field_def.field_name,
                    value=coerced,
                )
                wix_updated += bulk_result.succeeded
                wix_failed += bulk_result.failed
                for err in bulk_result.errors:
                    logger.warning("Wix bulk update error: %s", err)
            else:
                for pid in bulk_ids:
                    val = value_by_pid[pid]
                    result = self._call_details_update(pid, field_def.wix_property or field_def.field_name, val)
                    if result.succeeded:
                        wix_updated += 1
                    else:
                        wix_failed += 1
                        if result.errors:
                            logger.warning("Wix field update failed for %s: %s", pid, result.errors[0])

        return FieldBulkUpdateReport(
            requested=local_report.requested,
            changed=local_report.changed,
            skipped=local_report.skipped,
            failed=local_report.failed,
            dry_run=False,
            field_name=local_report.field_name,
            operator=local_report.operator,
            value=local_report.value,
            wix_attempted=wix_attempted,
            wix_updated=wix_updated,
            wix_failed=wix_failed,
            items=local_report.items,
        )

    def _build_report(
        self,
        skus: list[str],
        field_name: str,
        operator: str,
        value: str,
        dry_run: bool,
        wix_products: list[WixProduct] | None = None,
        local_products: list[ProductRow] | None = None,
    ) -> FieldBulkUpdateReport:
        """Build a report by simulating the update on all selected products."""
        selected = [sku.strip().upper() for sku in skus if sku.strip()]
        rows = local_products if local_products is not None else self._inventory.list_products()
        local_by_sku = {row.sku.strip().upper(): row for row in rows if row.sku.strip()}
        wix_by_sku = {row.sku.strip().upper(): row for row in (wix_products or []) if row.sku.strip()}
        items: list[FieldUpdateItem] = []
        changed_count = 0

        for sku in selected:
            row = local_by_sku.get(sku)
            wix_row = wix_by_sku.get(sku)
            if row is None and wix_row is None:
                items.append(
                    FieldUpdateItem(
                        sku=sku,
                        product_name=sku,
                        field_name=field_name,
                        old_value="",
                        new_value="",
                        status="failed",
                        message="SKU nicht gefunden",
                    )
                )
                continue

            old_val = self._get_effective_field_value(row, wix_row, field_name)
            product_name = (row.name if row is not None else "") or (wix_row.name if wix_row is not None else sku)
            try:
                new_val = self._compute_new_value(old_val, operator, value, field_name)
            except ValueError as exc:
                items.append(
                    FieldUpdateItem(
                        sku=sku,
                        product_name=product_name,
                        field_name=field_name,
                        old_value=str(old_val),
                        new_value="",
                        status="failed",
                        message=str(exc),
                    )
                )
                continue

            if str(old_val) == str(new_val):
                items.append(
                    FieldUpdateItem(
                        sku=sku,
                        product_name=product_name,
                        field_name=field_name,
                        old_value=str(old_val),
                        new_value=str(new_val),
                        status="skipped",
                    )
                )
            else:
                changed_count += 1
                items.append(
                    FieldUpdateItem(
                        sku=sku,
                        product_name=product_name,
                        field_name=field_name,
                        old_value=str(old_val),
                        new_value=str(new_val),
                        status="would-change" if dry_run else "changed",
                    )
                )

        return FieldBulkUpdateReport(
            requested=len(skus),
            changed=changed_count,
            skipped=sum(1 for item in items if item.status == "skipped"),
            failed=sum(1 for item in items if item.status == "failed"),
            dry_run=dry_run,
            field_name=field_name,
            operator=operator,
            value=value,
            items=items,
        )

    def _call_details_update(self, product_id: str, wix_field: str, value: str) -> object:
        """Dispatch to the appropriate WixProductDetailsClient method."""
        coerced = self._coerce_for_details(wix_field, value)
        dispatch = {
            "price": lambda: self._wix_client.update_product_price(product_id, price=float(coerced)),
            "compareAtPrice": lambda: self._wix_client.update_product_compare_at_price(product_id, compare_at_price=float(coerced) if coerced is not None else None),
            "cost": lambda: self._wix_client.update_product_cost(product_id, cost=float(coerced)),
            "weight": lambda: self._wix_client.update_product_weight(product_id, weight=float(coerced)),
            "visible": lambda: self._wix_client.update_product_visible(product_id, visible=bool(coerced)),
            "name": lambda: self._wix_client.update_product_name(product_id, name=str(coerced)),
            "description": lambda: self._wix_client.update_product_description(product_id, description=str(coerced)),
            "ribbon": lambda: self._wix_client.update_product_ribbon(product_id, ribbon=str(coerced)),
            "brand": lambda: self._wix_client.update_product_brand(product_id, brand_name=str(coerced)),
        }
        fn = dispatch.get(wix_field)
        if fn is not None:
            return fn()
        # Fallback for unknown / future fields
        return self._wix_client.bulk_update_property([product_id], field=wix_field, value=coerced)

    @staticmethod
    def _coerce_for_details(wix_field: str, value: str) -> Any:
        """Convert a string value to the correct Python type for WixProductDetailsClient."""
        if wix_field in {"price", "compareAtPrice", "cost", "weight"}:
            try:
                return round(float(value), 2)
            except (TypeError, ValueError):
                return None
        if wix_field == "visible":
            return str(value).lower() in ("true", "1", "yes", "ja")
        return value

    @staticmethod
    def _get_field_value(row: ProductRow, field_name: str) -> Any:
        """Extract field value from ProductRow."""
        if field_name == "price_eur":
            return row.price_eur or ""
        if field_name == "on_hand":
            return row.on_hand
        if field_name == "brand_name":
            return row.brand_name or ""
        if field_name == "category":
            return row.category or ""
        if field_name == "name":
            return row.name or ""
        raise ValueError(f"Unknown field: {field_name}")

    @staticmethod
    def _get_effective_field_value(
        row: ProductRow | None,
        wix_row: WixProduct | None,
        field_name: str,
    ) -> Any:
        if row is not None and field_name in {"price_eur", "on_hand", "brand_name", "category", "name"}:
            return ProductFieldBulkService._get_field_value(row, field_name)
        if wix_row is not None:
            if field_name == "price_eur":
                return wix_row.price or ""
            if field_name == "on_hand":
                return wix_row.inventory_quantity
            if field_name == "brand_name":
                return wix_row.brand_name or ""
            if field_name == "name":
                return wix_row.name or ""
            if field_name == "visible":
                return "true" if wix_row.visible else "false"
            return ""
        return ""

    @staticmethod
    def _set_field_on_row(row: ProductRow, field_name: str, value: Any) -> ProductRow:
        """Create updated ProductRow with new field value."""
        if field_name == "price_eur":
            return ProductRow(
                sku=row.sku,
                name=row.name,
                category=row.category,
                on_hand=row.on_hand,
                price_eur=str(value),
                wix_id=row.wix_id,
                sevdesk_id=row.sevdesk_id,
                brand_name=row.brand_name,
                brand_id=row.brand_id,
                print_file_path=row.print_file_path,
                print_profile_id=row.print_profile_id,
                print_plan=list(row.print_plan or []),
                title_print_configs=dict(row.title_print_configs or {}),
            )
        if field_name == "on_hand":
            return ProductRow(
                sku=row.sku,
                name=row.name,
                category=row.category,
                on_hand=int(value),
                price_eur=row.price_eur,
                wix_id=row.wix_id,
                sevdesk_id=row.sevdesk_id,
                brand_name=row.brand_name,
                brand_id=row.brand_id,
                print_file_path=row.print_file_path,
                print_profile_id=row.print_profile_id,
                print_plan=list(row.print_plan or []),
                title_print_configs=dict(row.title_print_configs or {}),
            )
        if field_name == "brand_name":
            return ProductRow(
                sku=row.sku,
                name=row.name,
                category=row.category,
                on_hand=row.on_hand,
                price_eur=row.price_eur,
                wix_id=row.wix_id,
                sevdesk_id=row.sevdesk_id,
                brand_name=str(value),
                brand_id=row.brand_id,
                print_file_path=row.print_file_path,
                print_profile_id=row.print_profile_id,
                print_plan=list(row.print_plan or []),
                title_print_configs=dict(row.title_print_configs or {}),
            )
        if field_name == "category":
            return ProductRow(
                sku=row.sku,
                name=row.name,
                category=str(value),
                on_hand=row.on_hand,
                price_eur=row.price_eur,
                wix_id=row.wix_id,
                sevdesk_id=row.sevdesk_id,
                brand_name=row.brand_name,
                brand_id=row.brand_id,
                print_file_path=row.print_file_path,
                print_profile_id=row.print_profile_id,
                print_plan=list(row.print_plan or []),
                title_print_configs=dict(row.title_print_configs or {}),
            )
        if field_name == "name":
            return ProductRow(
                sku=row.sku,
                name=str(value),
                category=row.category,
                on_hand=row.on_hand,
                price_eur=row.price_eur,
                wix_id=row.wix_id,
                sevdesk_id=row.sevdesk_id,
                brand_name=row.brand_name,
                brand_id=row.brand_id,
                print_file_path=row.print_file_path,
                print_profile_id=row.print_profile_id,
                print_plan=list(row.print_plan or []),
                title_print_configs=dict(row.title_print_configs or {}),
            )
        raise ValueError(f"Cannot set field: {field_name}")

    @staticmethod
    def _compute_new_value(old_value: Any, operator: str, input_value: str, field_name: str) -> Any:
        """Compute new value based on operator type."""
        op = FieldOperatorType(operator)

        if op == FieldOperatorType.SET:
            # For numeric fields, validate and parse
            if field_name == "on_hand":
                return int(input_value)
            if field_name in {"price_eur", "compare_at_price", "cost", "weight"}:
                return float(input_value)
            return input_value

        if op in (FieldOperatorType.ADD_PERCENT, FieldOperatorType.SUBTRACT_PERCENT):
            # Percentage operations only work on numeric fields
            if field_name not in ("price_eur", "on_hand", "compare_at_price", "cost", "weight"):
                raise ValueError(f"Percentage operations not supported for field {field_name}")

            try:
                percent = float(input_value)
                old_num = float(old_value) if old_value else 0.0
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Cannot parse numeric value: {old_value}") from exc

            if op == FieldOperatorType.ADD_PERCENT:
                new_num = old_num * (1 + percent / 100)
            else:  # SUBTRACT_PERCENT
                new_num = old_num * (1 - percent / 100)

            # Return formatted based on field type
            if field_name == "on_hand":
                return max(0, int(new_num))
            if field_name in {"price_eur", "compare_at_price", "cost", "weight"}:
                return round(new_num, 2)

        raise ValueError(f"Unknown operator: {operator}")
