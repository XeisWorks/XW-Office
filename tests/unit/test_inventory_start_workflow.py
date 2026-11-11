"""Tests for START preflight and execution workflow."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.core.config import AppConfig, PrintingSection
from xw_office.models.base import Base
from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.inventory.service import (
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

    def mutate_values_json(self, mutations: dict[str, object]) -> dict[str, str]:
        pending: dict[str, str] = {}
        for key, mutation in mutations.items():
            pending[key] = mutation(self.values.get(key))  # type: ignore[operator]
        self.values.update(pending)
        return pending


class _ShadowMirrorStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def mirror_absolute_stock(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return type("Result", (), {"status": "mirrored", "detail": "ok"})()

    def mirror_stock_movement(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return type("Result", (), {"status": "mirrored", "detail": "ok"})()


class _MasterStoreStub(_ShadowMirrorStub):
    def __init__(self, stock: dict[str, int]) -> None:
        super().__init__()
        self.stock = {str(key).upper(): int(value) for key, value in stock.items()}

    def load_stock_levels(self) -> dict[str, int]:
        return dict(self.stock)

    def mirror_absolute_stock(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        sku = str(kwargs["sku"]).upper()
        self.stock[sku] = int(kwargs["new_stock"])
        return type("Result", (), {"status": "mirrored", "detail": "ok"})()

    def mirror_stock_movement(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        sku = str(kwargs["sku"]).upper()
        target = self.stock.get(sku, 0) + int(kwargs["delta"])
        if target < 0:
            return type("Result", (), {"status": "shortage", "detail": "negative"})()
        self.stock[sku] = target
        return type("Result", (), {"status": "mirrored", "detail": "ok"})()


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


def test_manual_legacy_stock_update_is_mirrored_when_adapter_is_configured(tmp_path: Path) -> None:
    repo = _RepoStub(
        {
            "inventory.products": _product_payload(tmp_path / "score.pdf"),
            "inventory.stock_levels": json.dumps({"XW-6-003": 1}),
        }
    )
    mirror = _ShadowMirrorStub()
    service = InventoryService(AppConfig(), repo, shadow_mirror=mirror)

    service.set_product_stock("xw-6-003", 7)

    assert json.loads(repo.values["inventory.stock_levels"])["XW-6-003"] == 7
    assert mirror.calls == [{
        "sku": "XW-6-003",
        "new_stock": 7,
        "source": "legacy_inventory.set_product_stock",
        "external_reference": "inventory.stock_levels",
    }]


def test_direct_wix_fulfillment_sale_is_mirrored_without_touching_legacy_stock() -> None:
    repo = _RepoStub({"inventory.stock_levels": '{"XW-6-003": 9}'})
    mirror = _ShadowMirrorStub()
    service = InventoryService(AppConfig(), repo, shadow_mirror=mirror)

    service.record_wix_fulfillment_sale(
        sku="xw-6-003",
        quantity=2,
        invoice_id="invoice-1",
        order_reference="order-1",
        fulfillment_id="fulfillment-1",
    )

    assert json.loads(repo.values["inventory.stock_levels"])["XW-6-003"] == 9
    assert mirror.calls == [{
        "sku": "XW-6-003",
        "delta": -2,
        "reason": "sale",
        "source": "wix_fulfillment.direct",
        "external_reference": "wix-fulfillment:fulfillment-1;invoice:invoice-1;order:order-1",
        "idempotency_key": "wix-fulfillment:fulfillment-1:XW-6-003",
    }]


def test_confirmed_return_and_recount_update_legacy_stock_with_typed_shadow_reasons(
    tmp_path: Path,
) -> None:
    repo = _RepoStub(
        {
            "inventory.products": _product_payload(tmp_path / "score.pdf"),
            "inventory.stock_levels": '{"XW-6-003": 4}',
        }
    )
    mirror = _ShadowMirrorStub()
    service = InventoryService(AppConfig(), repo, shadow_mirror=mirror)

    returned = service.apply_stock_correction(
        sku="XW-6-003", reason="return", quantity=2, reference="RMA-42"
    )
    recounted = service.apply_stock_correction(
        sku="XW-6-003", reason="recount", target_stock=3, reference="INV-2026-09"
    )

    assert (returned.previous_stock, returned.new_stock, returned.delta) == (4, 6, 2)
    assert (recounted.previous_stock, recounted.new_stock, recounted.delta) == (6, 3, -3)
    assert json.loads(repo.values["inventory.stock_levels"])["XW-6-003"] == 3
    assert service.list_products()[0].on_hand == 3
    assert mirror.calls == [
        {
            "sku": "XW-6-003", "delta": 2, "reason": "return",
            "source": "legacy_inventory.manual_stock_correction",
            "external_reference": "inventory.stock_levels:return:RMA-42",
        },
        {
            "sku": "XW-6-003", "delta": -3, "reason": "recount",
            "source": "legacy_inventory.manual_stock_correction",
            "external_reference": "inventory.stock_levels:recount:INV-2026-09",
        },
    ]


def test_stock_correction_requires_a_reference_and_safe_input(tmp_path: Path) -> None:
    repo = _RepoStub(
        {
            "inventory.products": _product_payload(tmp_path / "score.pdf"),
            "inventory.stock_levels": '{"XW-6-003": 4}',
        }
    )
    service = InventoryService(AppConfig(), repo)

    with pytest.raises(RuntimeError, match="Referenz"):
        service.apply_stock_correction(
            sku="XW-6-003", reason="return", quantity=1, reference=""
        )
    with pytest.raises(RuntimeError, match="größer"):
        service.apply_stock_correction(
            sku="XW-6-003", reason="return", quantity=0, reference="RMA-0"
        )
    assert json.loads(repo.values["inventory.stock_levels"])["XW-6-003"] == 4


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
    mirror = _ShadowMirrorStub()
    service = InventoryService(cfg, repo, shadow_mirror=mirror)

    preflight = service.build_start_preflight(open_invoice_count=4)
    with patch("xw_office.services.inventory.service.print_pdf_by_plan") as mock_print:
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


def test_start_workflow_mirrors_print_and_sale_as_separate_ledger_reasons(tmp_path: Path) -> None:
    pdf_path = tmp_path / "score.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-6-003": 2}),
            "inventory.stock_levels": json.dumps({"XW-6-003": 1}),
            "inventory.products": _product_payload(pdf_path),
        }
    )
    mirror = _ShadowMirrorStub()
    service = InventoryService(AppConfig(printing=_printing_config()), repo, shadow_mirror=mirror)
    preflight = service.build_start_preflight(open_invoice_count=1)
    with patch("xw_office.services.inventory.service.print_pdf_by_plan"):
        service.execute_start_workflow(preflight, StartMode.INVOICES_AND_PRINT)

    assert mirror.calls == [
        {
            "sku": "XW-6-003", "delta": 4, "reason": "print_run",
            "source": "legacy_inventory.execute_start_workflow",
            "external_reference": "inventory.stock_levels",
            "idempotency_key": "start-print:XW-6-003:1:4",
        },
        {
            "sku": "XW-6-003", "delta": -2, "reason": "sale",
            "source": "legacy_inventory.execute_start_workflow",
            "external_reference": "inventory.stock_levels",
            "idempotency_key": "start-sale:XW-6-003:1:4:2",
        },
    ]


def test_start_workflow_can_skip_sale_shadow_when_invoice_booking_is_authoritative(tmp_path: Path) -> None:
    pdf_path = tmp_path / "score.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-6-003": 2}),
            "inventory.stock_levels": json.dumps({"XW-6-003": 3}),
            "inventory.products": _product_payload(pdf_path),
        }
    )
    mirror = _ShadowMirrorStub()
    service = InventoryService(AppConfig(printing=_printing_config()), repo, shadow_mirror=mirror)
    preflight = service.build_start_preflight(open_invoice_count=1)
    service.execute_start_workflow(
        preflight,
        StartMode.INVOICES_AND_PRINT,
        print_products=False,
        mirror_sales_to_hub=False,
    )
    assert mirror.calls == []


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

    with patch("xw_office.services.inventory.service.print_pdf_by_plan") as mock_print:
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


def test_invoice_consumption_is_per_document_idempotent_and_skips_unfinalized() -> None:
    repo = _RepoStub(
        {
            "inventory.stock_levels": json.dumps({"XW-6-003": 8}),
            "inventory.products": _product_payload(Path("unused.pdf")),
        }
    )
    mirror = _ShadowMirrorStub()
    service = InventoryService(AppConfig(), repo, shadow_mirror=mirror)

    report = service.execute_start_invoice_consumption(
        {
            "invoice-1": {"xw-6-003": 2},
            "invoice-2": {"XW-6-003": 3},
        },
        ["invoice-1"],
    )
    replay = service.execute_start_invoice_consumption(
        {"invoice-1": {"XW-6-003": 2}}, ["invoice-1"]
    )

    assert report.consumed_skus == ["XW-6-003"]
    assert report.stock_updated is True
    assert replay.stock_updated is False
    assert json.loads(repo.values["inventory.stock_levels"]) == {"XW-6-003": 6}
    assert json.loads(repo.values["inventory.invoice_consumption.v1"]) == {
        "invoice-1:XW-6-003": {
            "invoice_id": "invoice-1",
            "sku": "XW-6-003",
            "quantity": 2,
        }
    }
    assert len(mirror.calls) == 2
    assert mirror.calls[0]["idempotency_key"] == "start-invoice:invoice-1:XW-6-003"


def test_invoice_consumption_fails_without_partial_stock_or_journal_update() -> None:
    repo = _RepoStub(
        {
            "inventory.stock_levels": json.dumps({"XW-6-003": 1}),
            "inventory.products": _product_payload(Path("unused.pdf")),
        }
    )
    service = InventoryService(AppConfig(), repo)

    with pytest.raises(RuntimeError, match="reicht nicht"):
        service.execute_start_invoice_consumption(
            {"invoice-1": {"XW-6-003": 2}}, ["invoice-1"]
        )

    assert json.loads(repo.values["inventory.stock_levels"]) == {"XW-6-003": 1}
    assert "inventory.invoice_consumption.v1" not in repo.values


def test_invoice_consumption_database_transaction_rolls_back_all_keys() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[SettingKV.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    repository = SettingKvRepository(factory)
    repository.set_value_json("inventory.stock_levels", json.dumps({"XW-6-003": 1}))
    repository.set_value_json("inventory.products", _product_payload(Path("unused.pdf")))
    service = InventoryService(AppConfig(), repository)

    with pytest.raises(RuntimeError, match="reicht nicht"):
        service.execute_start_invoice_consumption(
            {"invoice-1": {"XW-6-003": 2}}, ["invoice-1"]
        )

    assert json.loads(repository.get_value_json("inventory.stock_levels") or "{}") == {
        "XW-6-003": 1
    }
    assert repository.get_value_json("inventory.invoice_consumption.v1") is None


def test_master_stock_update_uses_hub_without_writing_legacy_stock(tmp_path: Path) -> None:
    repo = _RepoStub(
        {
            "inventory.products": _product_payload(tmp_path / "score.pdf"),
            "inventory.stock_levels": json.dumps({"XW-6-003": 1}),
        }
    )
    master = _MasterStoreStub({"XW-6-003": 5})
    service = InventoryService(AppConfig(), repo, master_store=master, master_enabled=True)

    service.set_product_stock("xw-6-003", 7)

    assert master.stock["XW-6-003"] == 7
    assert json.loads(repo.values["inventory.stock_levels"]) == {"XW-6-003": 1}
    assert json.loads(repo.values["inventory.products"])[0]["on_hand"] == 7
    assert master.calls[0]["new_stock"] == 7


def test_master_invoice_consumption_books_hub_and_does_not_create_legacy_journal(
    tmp_path: Path,
) -> None:
    repo = _RepoStub(
        {
            "inventory.products": _product_payload(tmp_path / "score.pdf"),
            "inventory.stock_levels": json.dumps({"XW-6-003": 5}),
        }
    )
    master = _MasterStoreStub({"XW-6-003": 5})
    service = InventoryService(AppConfig(), repo, master_store=master, master_enabled=True)

    report = service.execute_start_invoice_consumption(
        {"invoice-1": {"XW-6-003": 2}}, ["invoice-1"]
    )

    assert report.stock_updated is True
    assert master.stock["XW-6-003"] == 3
    assert repo.values["inventory.stock_levels"] == json.dumps({"XW-6-003": 5})
    assert repo.get_value_json("inventory.invoice_consumption.v1") is None
    assert master.calls[0]["idempotency_key"] == "start-invoice:invoice-1:XW-6-003"


def test_master_stock_correction_uses_reasoned_hub_movement(tmp_path: Path) -> None:
    repo = _RepoStub(
        {
            "inventory.products": _product_payload(tmp_path / "score.pdf"),
            "inventory.stock_levels": json.dumps({"XW-6-003": 1}),
        }
    )
    master = _MasterStoreStub({"XW-6-003": 4})
    service = InventoryService(AppConfig(), repo, master_store=master, master_enabled=True)

    result = service.apply_stock_correction(
        sku="XW-6-003",
        reason="return",
        quantity=2,
        reference="RET-42",
    )

    assert result.previous_stock == 4
    assert result.new_stock == 6
    assert master.stock["XW-6-003"] == 6
    assert master.calls[0]["reason"] == "return"
    assert json.loads(repo.values["inventory.stock_levels"]) == {"XW-6-003": 1}


def test_build_reprint_preflight_identifies_low_stock() -> None:
    from xw_office.services.inventory.service import ReprintPreflight

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
    from xw_office.services.inventory.service import ReprintDecision, ReprintPreflight

    pdf_path = tmp_path / "score.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    repo = _RepoStub(
        {
            "inventory.stock_levels": json.dumps({"XW-6-003": 2}),
            "inventory.products": _product_payload(pdf_path),
        }
    )
    cfg = AppConfig(printing=_printing_config())
    mirror = _ShadowMirrorStub()
    service = InventoryService(cfg, repo, shadow_mirror=mirror)

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
    with patch("xw_office.services.inventory.service.print_pdf_by_plan") as mock_print:
        report = service.execute_reprint_workflow(preflight)

    assert report.stock_updated is True
    assert report.printed_skus == ["XW-6-003"]
    assert report.warnings == []
    mock_print.assert_called_once()

    stock_after = json.loads(repo.values["inventory.stock_levels"])
    # on_hand=2, printed=3 => 5, no invoice consumption
    assert stock_after["XW-6-003"] == 5
    assert mirror.calls == [{
        "sku": "XW-6-003", "delta": 3, "reason": "print_run",
        "source": "legacy_inventory.execute_reprint_workflow",
        "external_reference": "inventory.stock_levels",
        "idempotency_key": "reprint:XW-6-003:2:3",
    }]


def test_execute_start_workflow_skips_stock_increment_when_print_config_missing() -> None:
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-6-003": 2}),
            "inventory.stock_levels": json.dumps({"XW-6-003": 1}),
        }
    )
    service = InventoryService(AppConfig(printing=_printing_config()), repo)

    preflight = service.build_start_preflight(open_invoice_count=1)
    with patch("xw_office.services.inventory.service.print_pdf_by_plan") as mock_print:
        report = service.execute_start_workflow(preflight, StartMode.INVOICES_AND_PRINT)

    assert report.stock_updated is True
    assert report.printed_skus == []
    assert report.consumed_skus == ["XW-6-003"]
    assert report.warnings == ["XW-6-003: kein Produktdatensatz fuer Notendruck gefunden"]
    mock_print.assert_not_called()
    stock_after = json.loads(repo.values["inventory.stock_levels"])
    assert stock_after["XW-6-003"] == 0


def test_set_product_stock_updates_product_and_workflow_snapshots(tmp_path: Path) -> None:
    repo = _RepoStub(
        {
            "inventory.products": _product_payload(tmp_path / "score.pdf"),
            "inventory.stock_levels": json.dumps({"XW-6-003": 1, "OTHER": 4}),
        }
    )
    service = InventoryService(AppConfig(), repo)

    service.set_product_stock("xw-6-003", 7)

    products = json.loads(repo.values["inventory.products"])
    stock_levels = json.loads(repo.values["inventory.stock_levels"])
    assert products[0]["on_hand"] == 7
    assert stock_levels == {"XW-6-003": 7, "OTHER": 4}


def test_record_print_run_mirrors_print_reason_and_updates_legacy_snapshot(tmp_path: Path) -> None:
    repo = _RepoStub(
        {
            "inventory.products": _product_payload(tmp_path / "score.pdf"),
            "inventory.stock_levels": json.dumps({"XW-6-003": 1}),
        }
    )
    mirror = _ShadowMirrorStub()
    service = InventoryService(AppConfig(), repo, shadow_mirror=mirror)
    service.record_print_run(
        sku="XW-6-003", qty_printed=3, new_stock=4,
        external_reference="print-run:test", idempotency_key="print-run:test",
    )
    assert json.loads(repo.values["inventory.stock_levels"])["XW-6-003"] == 4
    assert mirror.calls == [{
        "sku": "XW-6-003", "delta": 3, "reason": "print_run",
        "source": "legacy_inventory.print_run", "external_reference": "print-run:test",
        "idempotency_key": "print-run:test",
    }]
