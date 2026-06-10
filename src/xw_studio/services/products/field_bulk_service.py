"""Product field bulk-edit service for targeted field updates.

Centralizes preview + apply logic for generic field changes (price, weight, categories, etc.)
Supports local DB + optional Wix writeback, with field-specific handling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from xw_studio.services.inventory.service import InventoryService, ProductRow
from xw_studio.services.wix.client import WixProductsClient


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

    def __init__(self, inventory: InventoryService, wix_client: WixProductsClient) -> None:
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
    ) -> FieldBulkUpdateReport:
        """Preview field update without persisting changes."""
        return self._build_report(
            skus=skus,
            field_name=field_name,
            operator=str(operator),
            value=value,
            dry_run=True,
        )

    def apply_field_update(
        self,
        skus: list[str],
        field_name: str,
        operator: FieldOperatorType | str,
        value: str,
        *,
        sync_wix: bool = False,
    ) -> FieldBulkUpdateReport:
        """Apply field update locally and optionally write to Wix."""
        local_report = self._apply_local_field_update(
            skus=skus,
            field_name=field_name,
            operator=str(operator),
            value=value,
        )
        if (not sync_wix) or local_report.changed <= 0:
            return local_report

        # Attempt Wix writeback
        return self._apply_wix_field_update(local_report)

    def _apply_local_field_update(
        self,
        skus: list[str],
        field_name: str,
        operator: str,
        value: str,
    ) -> FieldBulkUpdateReport:
        """Apply field update locally."""
        report = self._build_report(
            skus=skus,
            field_name=field_name,
            operator=operator,
            value=value,
            dry_run=False,
        )
        if report.changed <= 0:
            return report

        selected = {sku.strip().upper() for sku in skus if sku.strip()}
        updated_rows: list[ProductRow] = []
        items: list[FieldUpdateItem] = []

        for row in self._inventory.list_products():
            sku = row.sku.strip().upper()
            if sku not in selected:
                updated_rows.append(row)
                continue

            # Calculate new value based on operator
            old_val = self._get_field_value(row, field_name)
            try:
                new_val = self._compute_new_value(old_val, operator, value, field_name)
            except ValueError as exc:
                items.append(
                    FieldUpdateItem(
                        sku=row.sku,
                        product_name=row.name,
                        field_name=field_name,
                        old_value=str(old_val),
                        new_value="",
                        status="failed",
                        message=str(exc),
                    )
                )
                updated_rows.append(row)
                continue

            if str(old_val) == str(new_val):
                items.append(
                    FieldUpdateItem(
                        sku=row.sku,
                        product_name=row.name,
                        field_name=field_name,
                        old_value=str(old_val),
                        new_value=str(new_val),
                        status="skipped",
                    )
                )
                updated_rows.append(row)
                continue

            # Update the row with new field value
            updated_row = self._set_field_on_row(row, field_name, new_val)
            updated_rows.append(updated_row)

            items.append(
                FieldUpdateItem(
                    sku=row.sku,
                    product_name=row.name,
                    field_name=field_name,
                    old_value=str(old_val),
                    new_value=str(new_val),
                    status="changed",
                )
            )

        # Persist
        self._inventory.save_products(updated_rows)

        return FieldBulkUpdateReport(
            requested=len(skus),
            changed=sum(1 for item in items if item.status == "changed"),
            skipped=sum(1 for item in items if item.status == "skipped"),
            failed=sum(1 for item in items if item.status == "failed"),
            dry_run=False,
            field_name=field_name,
            operator=operator,
            value=value,
            items=items,
        )

    def _apply_wix_field_update(self, local_report: FieldBulkUpdateReport) -> FieldBulkUpdateReport:
        """Write field updates to Wix (best-effort)."""
        if not self._wix_client.has_credentials():
            return local_report

        field_def = BULK_EDITABLE_FIELDS.get(local_report.field_name)
        if not field_def or not field_def.writable_wix:
            return local_report

        wix_attempted = 0
        wix_updated = 0
        wix_failed = 0

        for item in local_report.items:
            if item.status != "changed":
                continue

            # Find the product's Wix ID from local DB
            all_products = self._inventory.list_products()
            product = next((p for p in all_products if p.sku.strip().upper() == item.sku.strip().upper()), None)
            if not product or not product.wix_id:
                wix_failed += 1
                continue

            wix_attempted += 1
            try:
                self._wix_client.update_product_field(
                    product_id=product.wix_id,
                    field_name=field_def.wix_property or field_def.field_name,
                    value=item.new_value,
                )
                wix_updated += 1
            except Exception as exc:  # noqa: BLE001
                wix_failed += 1
                logger.warning(
                    "Wix field update failed for product %s: %s",
                    product.wix_id,
                    exc,
                )

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
    ) -> FieldBulkUpdateReport:
        """Build a report by simulating the update on all selected products."""
        selected = {sku.strip().upper() for sku in skus if sku.strip()}
        items: list[FieldUpdateItem] = []
        changed_count = 0

        for row in self._inventory.list_products():
            sku = row.sku.strip().upper()
            if sku not in selected:
                continue

            old_val = self._get_field_value(row, field_name)
            try:
                new_val = self._compute_new_value(old_val, operator, value, field_name)
            except ValueError as exc:
                items.append(
                    FieldUpdateItem(
                        sku=row.sku,
                        product_name=row.name,
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
                        sku=row.sku,
                        product_name=row.name,
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
                        sku=row.sku,
                        product_name=row.name,
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
            if field_name == "price_eur":
                return float(input_value)
            return input_value

        if op in (FieldOperatorType.ADD_PERCENT, FieldOperatorType.SUBTRACT_PERCENT):
            # Percentage operations only work on numeric fields
            if field_name not in ("price_eur", "on_hand"):
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
            if field_name == "price_eur":
                return round(new_num, 2)

        raise ValueError(f"Unknown operator: {operator}")


import logging

logger = logging.getLogger(__name__)
