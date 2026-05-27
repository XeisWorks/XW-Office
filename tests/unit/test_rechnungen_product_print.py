from __future__ import annotations

import fitz

from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container
from xw_studio.services.products.catalog import Product
from xw_studio.services.products.print_decision import PieceBlock
from xw_studio.services.printing.print_queue import PrintQueueService
from xw_studio.ui.modules.rechnungen.print_dialog import prepare_piece_pdf_print


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
