from __future__ import annotations

import datetime as dt

from xw_office.services.product_hub.inventory_audit import (
    InventoryAuditRow,
    audit_inventory_sources,
)


def test_audit_reports_mapping_drift_and_missing_sellable_date() -> None:
    report = audit_inventory_sources(
        [
            InventoryAuditRow(
                sku=" n-001 ",
                title="Marsch",
                sevdesk_part_id="part-1",
                legacy_on_hand=12,
                hub_on_hand=10,
            ),
            InventoryAuditRow(sku="POD-001", title="POD", article_kind="pod"),
            InventoryAuditRow(sku="DIG-001", title="Digital", article_kind="digital"),
        ]
    )

    assert report.active_physical_count == 2
    assert report.mapped_physical_count == 1
    assert report.legacy_hub_drift_count == 1
    assert report.missing_sellable_since_count == 2
    assert report.blocking_issue_count == 1
    assert {issue.code for issue in report.issues} >= {
        "missing_sevdesk_mapping",
        "legacy_hub_drift",
        "missing_sellable_since",
    }


def test_audit_detects_duplicate_and_negative_quantities() -> None:
    report = audit_inventory_sources(
        [
            InventoryAuditRow(
                sku="N-001",
                article_kind="external_print",
                sevdesk_part_id="part-1",
                legacy_on_hand=-1,
                hub_on_hand=0,
                sellable_since=dt.date(2026, 1, 1),
            ),
            InventoryAuditRow(
                sku="n-001",
                article_kind="external_print",
                sevdesk_part_id="part-2",
                legacy_on_hand=0,
                hub_on_hand=0,
                sellable_since=dt.date(2026, 1, 1),
            ),
        ]
    )

    assert report.ready_for_inventory is False
    assert [issue.code for issue in report.issues].count("duplicate_sku") == 2
    assert [issue.code for issue in report.issues].count("negative_source_quantity") == 1


def test_digital_products_do_not_require_stock_mapping_or_quantities() -> None:
    report = audit_inventory_sources(
        [InventoryAuditRow(sku="DIG-001", article_kind="digital", sevdesk_part_id="")]
    )

    assert report.active_physical_count == 0
    assert report.mapped_physical_count == 0
    assert report.issues == ()
    assert report.ready_for_inventory is True
