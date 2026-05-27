from __future__ import annotations

import fitz

from xw_studio.core.config import AppConfig, PrintingSection
from xw_studio.core.container import Container
from xw_studio.services.inventory import InventoryService
from xw_studio.services.products.catalog import Product
from xw_studio.services.products.catalog import ProductCatalogService
from xw_studio.services.products.print_decision import PieceBlock
from xw_studio.services.printing.print_queue import PrintQueueService
from xw_studio.ui.modules.rechnungen import print_dialog
from xw_studio.ui.modules.rechnungen.print_dialog import ProductPrintConfigDialog, prepare_piece_pdf_print


def test_prepare_piece_pdf_print_uses_requested_copy_count(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "piece.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    piece = PieceBlock(
        sku="XW-443",
        name="Test Piece",
        qty_needed=1,
        print_profile_id="noten_duplex",
        product=Product(id="p1", sku="XW-443", name="Test Piece", print_file_path=str(pdf_path)),
    )
    container = Container(AppConfig())
    queue = object()
    container.register(PrintQueueService, lambda _container: queue)  # type: ignore[return-value]
    captured: dict[str, object] = {}

    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.print_dialog._check_printer_runtime", lambda *_args: True)

    def fake_print_pdf_by_plan(
        pdf_path_arg: str,
        printing: object,
        *,
        print_plan: list[dict[str, str]] | None = None,
        profile_id: str = "",
        copies: int = 1,
        page_count: int | None = None,
        print_queue: object | None = None,
        job_kind: str = "",
    ) -> None:
        captured.update(
            {
                "pdf_path": pdf_path_arg,
                "profile_id": profile_id,
                "copies": copies,
                "page_count": page_count,
                "print_queue": print_queue,
                "job_kind": job_kind,
            }
        )

    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.print_dialog.print_pdf_by_plan", fake_print_pdf_by_plan)

    job = prepare_piece_pdf_print(None, container, piece=piece, copies=7)  # type: ignore[arg-type]

    assert job is not None
    job()
    assert captured == {
        "pdf_path": str(pdf_path),
        "profile_id": "noten_duplex",
        "copies": 7,
        "page_count": 1,
        "print_queue": queue,
        "job_kind": "product",
    }


def test_prepare_piece_pdf_print_prompts_for_missing_print_config(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "piece.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    piece = PieceBlock(
        sku="XW-4553",
        name="Missing Config Piece",
        qty_needed=1,
        product=Product(id="p1", sku="XW-4553", name="Missing Config Piece"),
    )
    container = Container(AppConfig())
    queue = object()
    container.register(PrintQueueService, lambda _container: queue)  # type: ignore[return-value]

    saved: dict[str, object] = {}

    class InventoryStub:
        def save_product_print_config(self, **kwargs: object) -> object:
            saved.update(kwargs)
            return object()

    class CatalogStub:
        def reload_from_settings(self) -> None:
            saved["reloaded"] = True

    class DialogStub:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def exec(self) -> object:
            return print_dialog.QDialog.DialogCode.Accepted

        def values(self) -> tuple[str, str, list[dict[str, str]]]:
            return str(pdf_path), "noten_duplex", [{"range": "Alle Seiten", "profile_id": "noten_duplex"}]

    captured: dict[str, object] = {}

    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.print_dialog._check_printer_runtime", lambda *_args: True)
    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.print_dialog.ProductPrintConfigDialog", DialogStub)
    container.register(InventoryService, lambda _container: InventoryStub())  # type: ignore[return-value]
    container.register(ProductCatalogService, lambda _container: CatalogStub())  # type: ignore[return-value]

    def fake_print_pdf_by_plan(
        pdf_path_arg: str,
        printing: object,
        *,
        print_plan: list[dict[str, str]] | None = None,
        profile_id: str = "",
        copies: int = 1,
        page_count: int | None = None,
        print_queue: object | None = None,
        job_kind: str = "",
    ) -> None:
        captured.update(
            {
                "pdf_path": pdf_path_arg,
                "profile_id": profile_id,
                "print_plan": print_plan,
                "copies": copies,
                "page_count": page_count,
                "print_queue": print_queue,
                "job_kind": job_kind,
            }
        )

    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.print_dialog.print_pdf_by_plan", fake_print_pdf_by_plan)

    job = prepare_piece_pdf_print(None, container, piece=piece, copies=2)  # type: ignore[arg-type]

    assert job is not None
    assert saved["sku"] == "XW-4553"
    assert saved["print_file_path"] == str(pdf_path)
    assert saved["print_profile_id"] == "noten_duplex"
    assert saved["reloaded"] is True
    job()
    assert captured["pdf_path"] == str(pdf_path)
    assert captured["profile_id"] == "noten_duplex"
    assert captured["print_plan"] == [{"range": "Alle Seiten", "profile_id": "noten_duplex"}]
    assert captured["copies"] == 2


def test_product_print_config_dialog_builds_plan_rows_with_start_end(qtbot: object, tmp_path) -> None:
    pdf_path = tmp_path / "piece.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    config = AppConfig(
        printing=PrintingSection(
            print_profiles=[
                {"id": "noten_duplex", "label": "Noten Duplex", "printer_name": "Printer A"},
                {"id": "brochure_mono", "label": "Broschuere", "printer_name": "Printer B"},
            ]
        )
    )
    container = Container(config)
    piece = PieceBlock(
        sku="XW-4553",
        name="Missing Config Piece",
        qty_needed=1,
        print_plan=[{"range": "START-END", "profile_id": "brochure_mono"}],
        product=Product(id="p1", sku="XW-4553", name="Missing Config Piece", print_file_path=str(pdf_path)),
    )

    dialog = ProductPrintConfigDialog(None, container, piece)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    path, profile_id, plan = dialog.values()

    assert path == str(pdf_path)
    assert profile_id == "brochure_mono"
    assert plan == [{"range": "START-END", "profile_id": "brochure_mono"}]
