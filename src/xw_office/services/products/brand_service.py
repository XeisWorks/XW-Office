"""Brand bulk-edit service for product pipeline workflows.

Centralizes preview + apply logic so UI modules keep orchestration-only code.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from xw_office.services.inventory.service import InventoryService, ProductRow
from xw_office.services.wix.client import WixProductsClient


@dataclass(frozen=True)
class BrandUpdateItem:
    """Result for one SKU in a brand update run."""

    sku: str
    name: str
    category: str
    previous_brand: str
    new_brand: str
    status: str
    message: str = ""


@dataclass(frozen=True)
class BrandBulkUpdateReport:
    """Aggregated dry-run/apply report for brand updates."""

    requested: int
    changed: int
    skipped: int
    failed: int
    dry_run: bool
    wix_attempted: int = 0
    wix_updated: int = 0
    wix_failed: int = 0
    wix_brand_resolved: bool = False
    wix_brand_created: bool = False
    items: list[BrandUpdateItem] = field(default_factory=list)


class ProductBrandService:
    """Service for targeted and bulk brand updates on local product records."""

    def __init__(self, inventory: InventoryService, wix_client: WixProductsClient) -> None:
        self._inventory = inventory
        self._wix_client = wix_client

    def list_products(self) -> list[ProductRow]:
        """Return all local product rows from the inventory store."""
        return self._inventory.list_products()

    def preview_local_brand_update(self, skus: list[str], new_brand: str) -> BrandBulkUpdateReport:
        """Preview brand update without persisting changes."""
        return self._build_report(skus=skus, new_brand=new_brand, dry_run=True)

    def apply_local_brand_update(self, skus: list[str], new_brand: str) -> BrandBulkUpdateReport:
        """Apply brand update to selected local products and persist."""
        report = self._build_report(skus=skus, new_brand=new_brand, dry_run=False)
        if report.changed <= 0:
            return report

        selected = {sku.strip().upper() for sku in skus if sku.strip()}
        target_brand = new_brand.strip()
        updates: dict[str, dict[str, object]] = {}
        rows = self._inventory.list_products()
        for row in rows:
            sku = row.sku.strip().upper()
            if sku in selected and (row.brand_name or "").strip() != target_brand:
                updates[sku] = {"brand_name": target_brand}
        atomic_update = getattr(self._inventory, "update_product_fields", None)
        if callable(atomic_update):
            atomic_update(updates)
        else:
            self._inventory.save_products(
                [replace(row, brand_name=target_brand) if row.sku.strip().upper() in updates else row for row in rows]
            )
        return report

    def apply_brand_update(
        self,
        skus: list[str],
        new_brand: str,
        *,
        sync_wix: bool,
        create_missing_wix_brand: bool,
    ) -> BrandBulkUpdateReport:
        """Apply brand update locally and optionally write it back to Wix."""
        local_report = self.apply_local_brand_update(skus, new_brand)
        if (not sync_wix) or local_report.changed <= 0:
            return local_report

        items = list(local_report.items)
        item_by_sku = {item.sku.strip().upper(): item for item in items}

        wix_attempted = 0
        wix_updated = 0
        wix_failed = 0
        wix_brand_resolved = False
        wix_brand_created = False
        resolved_brand_id = ""

        if self._wix_client.has_credentials() and self._wix_client.supports_brand_catalog():
            try:
                before_ids = {
                    str(item.get("id") or "").strip()
                    for item in self._wix_client.list_brands()
                    if str(item.get("id") or "").strip()
                }
                resolved_brand_id = self._wix_client.ensure_brand(
                    new_brand,
                    create_if_missing=create_missing_wix_brand,
                )
                wix_brand_resolved = bool(resolved_brand_id)
                if resolved_brand_id and resolved_brand_id not in before_ids:
                    wix_brand_created = True
            except Exception:
                # Fallback: update by brand name only
                resolved_brand_id = ""

        rows_by_sku = {row.sku.strip().upper(): row for row in self._inventory.list_products() if row.sku.strip()}
        missing_wix_ids = [
            sku for sku, row in rows_by_sku.items()
            if sku in {s.strip().upper() for s in skus} and not str(row.wix_id or "").strip()
        ]

        wix_ids_by_sku: dict[str, str] = {}
        if missing_wix_ids and self._wix_client.has_credentials():
            for wix_row in self._wix_client.list_products():
                sku = str(wix_row.sku or "").strip().upper()
                if sku and sku in missing_wix_ids and str(wix_row.id or "").strip():
                    wix_ids_by_sku[sku] = str(wix_row.id or "").strip()

        for sku, row in rows_by_sku.items():
            if sku not in item_by_sku:
                continue
            item = item_by_sku[sku]
            if item.status not in ("changed", "would-change"):
                continue
            product_id = str(row.wix_id or "").strip() or wix_ids_by_sku.get(sku, "")
            if not product_id:
                wix_failed += 1
                replacement = BrandUpdateItem(
                    sku=item.sku,
                    name=item.name,
                    category=item.category,
                    previous_brand=item.previous_brand,
                    new_brand=item.new_brand,
                    status="failed",
                    message="Kein Wix-Produkt zugeordnet",
                )
                items[items.index(item)] = replacement
                continue

            wix_attempted += 1
            try:
                self._wix_client.update_product_brand(
                    product_id,
                    brand_name=new_brand,
                    brand_id=resolved_brand_id or row.brand_id,
                )
                wix_updated += 1
            except Exception as exc:  # noqa: BLE001
                wix_failed += 1
                replacement = BrandUpdateItem(
                    sku=item.sku,
                    name=item.name,
                    category=item.category,
                    previous_brand=item.previous_brand,
                    new_brand=item.new_brand,
                    status="failed",
                    message=f"Wix-Writeback fehlgeschlagen: {exc}",
                )
                items[items.index(item)] = replacement

        return BrandBulkUpdateReport(
            requested=local_report.requested,
            changed=local_report.changed,
            skipped=local_report.skipped,
            failed=wix_failed,
            dry_run=local_report.dry_run,
            wix_attempted=wix_attempted,
            wix_updated=wix_updated,
            wix_failed=wix_failed,
            wix_brand_resolved=wix_brand_resolved,
            wix_brand_created=wix_brand_created,
            items=items,
        )

    def _build_report(self, *, skus: list[str], new_brand: str, dry_run: bool) -> BrandBulkUpdateReport:
        target_brand = new_brand.strip()
        selected = {sku.strip().upper() for sku in skus if sku.strip()}
        if not selected:
            return BrandBulkUpdateReport(
                requested=0,
                changed=0,
                skipped=0,
                failed=0,
                dry_run=dry_run,
                wix_attempted=0,
                wix_updated=0,
                wix_failed=0,
                wix_brand_resolved=False,
                wix_brand_created=False,
                items=[],
            )

        items: list[BrandUpdateItem] = []
        changed = 0
        skipped = 0

        by_sku = {row.sku.strip().upper(): row for row in self._inventory.list_products() if row.sku.strip()}
        for sku in sorted(selected):
            row = by_sku.get(sku)
            if row is None:
                skipped += 1
                items.append(
                    BrandUpdateItem(
                        sku=sku,
                        name="",
                        category="",
                        previous_brand="",
                        new_brand=target_brand,
                        status="skipped",
                        message="SKU lokal nicht gefunden",
                    )
                )
                continue

            previous_brand = (row.brand_name or "").strip()
            if previous_brand == target_brand:
                skipped += 1
                items.append(
                    BrandUpdateItem(
                        sku=row.sku,
                        name=row.name,
                        category=row.category,
                        previous_brand=previous_brand,
                        new_brand=target_brand,
                        status="skipped",
                        message="Brand bereits gesetzt",
                    )
                )
                continue

            changed += 1
            items.append(
                BrandUpdateItem(
                    sku=row.sku,
                    name=row.name,
                    category=row.category,
                    previous_brand=previous_brand,
                    new_brand=target_brand,
                    status="would-change" if dry_run else "changed",
                    message="",
                )
            )

        return BrandBulkUpdateReport(
            requested=len(selected),
            changed=changed,
            skipped=skipped,
            failed=0,
            dry_run=dry_run,
            wix_attempted=0,
            wix_updated=0,
            wix_failed=0,
            wix_brand_resolved=False,
            wix_brand_created=False,
            items=items,
        )
