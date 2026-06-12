"""Tests for START preflight and execution workflow."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from xw_studio.core.config import AppConfig, PrintingSection
from xw_studio.services.inventory.service import (
    InventoryService,
    StartMode,
)


class _RepoStub:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self.values[key] = value_json


def _printing_config() -> PrintingSection:
    return PrintingSection(
        buffer_quantity=3,
        print_profiles=[
            {
                "id": "noten_a4_duplex",
                "label": "Noten A4 Duplex",
                "printer_name": "Rechnungen",
                "dpi": 600,
            }
        ],
    )


def _product_payload(pdf_path: Path) -> str:
    return json.dumps(
        [
            {
                "sku": "XW-6-003",
                "name": "Test Piece",
                "category": "Noten",
                "on_hand": 0,
                "price_eur": "0",
                "wix_id": "",
                "sevdesk_id": "",
                "print_file_path": str(pdf_path),
                "print_profile_id": "noten_a4_duplex",
                "print_plan": [],
            }
        ]
    )


def test_preflight_prints_only_when_stock_insufficient() -> None:
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-4-001": 5, "XW-6-003": 2}),
            "inventory.stock_levels": json.dumps({"XW-4-001": 5, "XW-6-003": 1}),
        }
    )
    cfg = AppConfig(printing=PrintingSection(buffer_quantity=3))
    service = InventoryService(cfg, repo)

    preflight = service.build_start_preflight(open_invoice_count=4)

    assert preflight.missing_position_data is False
    by_sku = {d.sku: d for d in preflight.decisions}

    assert by_sku["XW-4-001"].will_print is False
    assert by_sku["XW-4-001"].final_print_qty == 0
    assert by_sku["XW-6-003"].will_print is True
    assert by_sku["XW-6-003"].missing_qty == 1
    assert by_sku["XW-6-003"].final_print_qty == 4


def test_execute_full_mode_updates_stock_with_buffer_and_consumption(tmp_path: Path) -> None:
    pdf_path = tmp_path / "score.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-4-001": 5, "XW-6-003": 2}),
            "inventory.stock_levels": json.dumps({"XW-4-001": 5, "XW-6-003": 1}),
            "inventory.products": _product_payload(pdf_path),
        }
    )
    cfg = AppConfig(printing=_printing_config())
    service = InventoryService(cfg, repo)

    preflight = service.build_start_preflight(open_invoice_count=4)
    with patch("xw_studio.services.inventory.service.print_pdf_by_plan") as mock_print:
        report = service.execute_start_workflow(preflight, StartMode.INVOICES_AND_PRINT)

    assert report.stock_updated is True
    assert report.printed_skus == ["XW-6-003"]
    assert report.warnings == []
    mock_print.assert_called_once()

    stock_after = json.loads(repo.values["inventory.stock_levels"])
    # XW-4-001: on_hand=5, required=5, printed=0 -> 0
    assert stock_after["XW-4-001"] == 0
    # XW-6-003: on_hand=1, required=2, printed=(1+3)=4 -> 3
    assert stock_after["XW-6-003"] == 3


def test_print_only_then_consumption_does_not_print_twice(tmp_path: Path) -> None:
    pdf_path = tmp_path / "score.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-6-003": 2}),
            "inventory.stock_levels": json.dumps({"XW-6-003": 1}),
            "inventory.products": _product_payload(pdf_path),
        }
    )
    service = InventoryService(AppConfig(printing=_printing_config()), repo)
    preflight = service.build_start_preflight(open_invoice_count=1)

    with patch("xw_studio.services.inventory.service.print_pdf_by_plan") as mock_print:
        print_report = service.execute_start_workflow(preflight, StartMode.PRINT_ONLY)
        consume_report = service.execute_start_workflow(
            preflight,
            StartMode.INVOICES_AND_PRINT,
            print_products=False,
        )

    assert print_report.printed_skus == ["XW-6-003"]
    assert print_report.consumed_skus == []
    assert consume_report.printed_skus == []
    assert consume_report.consumed_skus == ["XW-6-003"]
    mock_print.assert_called_once()
    assert json.loads(repo.values["inventory.stock_levels"])["XW-6-003"] == 3


def test_execute_invoices_mode_keeps_stock_unchanged() -> None:
    raw_stock = json.dumps({"XW-7-100": 9})
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-7-100": 2}),
            "inventory.stock_levels": raw_stock,
        }
    )
    service = InventoryService(AppConfig(), repo)

    preflight = service.build_start_preflight(open_invoice_count=2)
    report = service.execute_start_workflow(preflight, StartMode.INVOICES_ONLY)

    assert report.stock_updated is False
    assert repo.values["inventory.stock_levels"] == raw_stock


def test_build_reprint_preflight_identifies_low_stock() -> None:
    from xw_studio.services.inventory.service import ReprintPreflight

    repo = _RepoStub(
        {
            "inventory.stock_levels": json.dumps({"XW-4-001": 10, "XW-6-003": 2}),
        }
    )
    cfg = AppConfig(printing=PrintingSection(buffer_quantity=3))
    service = InventoryService(cfg, repo)

    requirements = {"XW-4-001": 1, "XW-6-003": 1}
    preflight = service.build_reprint_preflight(requirements)

    assert isinstance(preflight, ReprintPreflight)
    assert preflight.missing_position_data is False
    by_sku = {d.sku: d for d in preflight.decisions}

    # XW-4-001: on_hand=10, min_target=5 => will_print=False
    assert by_sku["XW-4-001"].will_print is False
    assert by_sku["XW-4-001"].final_print_qty == 0

    # XW-6-003: on_hand=2, min_target=5 => will_print=True, final=3
    assert by_sku["XW-6-003"].will_print is True
    assert by_sku["XW-6-003"].final_print_qty == 3


def test_execute_reprint_workflow_only_adds_printed_stock(tmp_path: Path) -> None:
    from xw_studio.services.inventory.service import ReprintDecision, ReprintPreflight

    pdf_path = tmp_path / "score.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    repo = _RepoStub(
        {
            "inventory.stock_levels": json.dumps({"XW-6-003": 2}),
            "inventory.products": _product_payload(pdf_path),
        }
    )
    cfg = AppConfig(printing=_printing_config())
    service = InventoryService(cfg, repo)

    decisions = [
        ReprintDecision(
            sku="XW-6-003",
            on_hand_qty=2,
            min_stock_target=5,
            reprint_batch_qty=3,
            will_print=True,
            final_print_qty=3,
        )
    ]
    preflight = ReprintPreflight(decisions=decisions, missing_position_data=False)
    with patch("xw_studio.services.inventory.service.print_pdf_by_plan") as mock_print:
        report = service.execute_reprint_workflow(preflight)

    assert report.stock_updated is True
    assert report.printed_skus == ["XW-6-003"]
    assert report.warnings == []
    mock_print.assert_called_once()

    stock_after = json.loads(repo.values["inventory.stock_levels"])
    # on_hand=2, printed=3 => 5, no invoice consumption
    assert stock_after["XW-6-003"] == 5


def test_execute_start_workflow_skips_stock_increment_when_print_config_missing() -> None:
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-6-003": 2}),
            "inventory.stock_levels": json.dumps({"XW-6-003": 1}),
        }
    )
    service = InventoryService(AppConfig(printing=_printing_config()), repo)

    preflight = service.build_start_preflight(open_invoice_count=1)
    with patch("xw_studio.services.inventory.service.print_pdf_by_plan") as mock_print:
        report = service.execute_start_workflow(preflight, StartMode.INVOICES_AND_PRINT)

    assert report.stock_updated is True
    assert report.printed_skus == []
    assert report.consumed_skus == ["XW-6-003"]
    assert report.warnings == ["XW-6-003: kein Produktdatensatz fuer Notendruck gefunden"]
    mock_print.assert_not_called()
    stock_after = json.loads(repo.values["inventory.stock_levels"])
    assert stock_after["XW-6-003"] == 0
