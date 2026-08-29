from __future__ import annotations

import fitz
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QComboBox, QStyleOptionViewItem

from xw_office.core.config import AppConfig, PrintingSection
from xw_office.core.container import Container
from xw_office.services.background_jobs import BackgroundJobManager
from xw_office.services.inventory import InventoryService
from xw_office.services.products.catalog import Product
from xw_office.services.products.catalog import ProductCatalogService
from xw_office.services.products.print_decision import PieceBlock
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.ui.modules.rechnungen import print_dialog
from xw_office.ui.modules.rechnungen.print_dialog import ProductPrintConfigDialog, prepare_piece_pdf_print
from xw_office.ui.modules.rechnungen.view import _PieceDelegate


def test_selected_product_delegate_has_exactly_one_print_or_settings_action() -> None:
    """The row always carries a qty stepper; the single action button next
    to it must still be exclusively "print" xor "manage", never both."""
    row = QRect(0, 0, 420, 82)

    with_config = set(_PieceDelegate._button_rects(row, has_print_config=True))
    without_config = set(_PieceDelegate._button_rects(row, has_print_config=False))

    assert with_config == {"print", "qty_minus", "qty_plus"}
    assert without_config == {"manage", "qty_minus", "qty_plus"}
    assert with_config.isdisjoint({"manage"})
    assert without_config.isdisjoint({"print"})


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

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog._check_printer_runtime", lambda *_args: True)

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

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog.print_pdf_by_plan", fake_print_pdf_by_plan)

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
        def resolve_product_title(self, _sku: str, title: str) -> str:
            return title

        def resolve_print_config(self, _sku: str, *, title: str = "") -> dict[str, object]:
            if not saved.get("print_file_path"):
                return {}
            return {
                "path": saved["print_file_path"],
                "profile_id": saved["print_profile_id"],
                "print_plan": saved["print_plan"],
            }

        def resolve_sku(self, _sku: str) -> Product | None:
            return piece.product

        def reload_from_settings(self) -> None:
            saved["reloaded"] = True

    class BackgroundJobsMustNotBeUsed:
        def submit_callable(self, **_kwargs: object) -> None:
            raise AssertionError("Print config persistence must finish before the dialog reports success")

    class DialogStub:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def exec(self) -> object:
            return print_dialog.QDialog.DialogCode.Accepted

        def values(self) -> tuple[str, str, list[dict[str, str]]]:
            return str(pdf_path), "noten_duplex", [{"range": "Alle Seiten", "profile_id": "noten_duplex"}]

    captured: dict[str, object] = {}

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog._check_printer_runtime", lambda *_args: True)
    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog.ProductPrintConfigDialog", DialogStub)
    container.register(InventoryService, lambda _container: InventoryStub())  # type: ignore[return-value]
    container.register(ProductCatalogService, lambda _container: CatalogStub())  # type: ignore[return-value]
    container.register(BackgroundJobManager, lambda _container: BackgroundJobsMustNotBeUsed())  # type: ignore[return-value]

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

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog.print_pdf_by_plan", fake_print_pdf_by_plan)

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
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()
    config = AppConfig(
        printing=PrintingSection(
            print_profiles=[
                {"id": "invoice", "label": "Rechnungsdruck", "printer_name": "Rechnungen"},
                {"id": "noten_duplex", "label": "Noten Duplex", "printer_name": "Printer A"},
                {
                    "id": "noten_native_pilot",
                    "label": "Pilot",
                    "printer_name": "Printer A",
                    "backend": "pdf_xchange",
                },
                {"id": "noten_a5", "label": "Noten A5", "printer_name": "Printer A5"},
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
    assert "2 Seite(n)" in dialog._pdf_status.text()  # noqa: SLF001
    assert "Printer B" in dialog._plan_summary.text()  # noqa: SLF001
    assert "Broschuere" not in dialog._plan_summary.text()  # noqa: SLF001
    assert "BACKEND" not in dialog._plan_summary.text()  # noqa: SLF001
    assert dialog._plan_model.columnCount() == 2  # noqa: SLF001
    assert dialog._plan_model.headerData(1, Qt.Orientation.Horizontal) == "Drucker"  # noqa: SLF001
    profile_ids = [profile_id for profile_id, _label, _printer, _backend in dialog._profiles]  # noqa: SLF001
    assert "invoice" not in profile_ids
    assert "noten_native_pilot" not in profile_ids
    assert "noten_a5" in profile_ids


def test_print_plan_summary_flags_gap_and_overlap(qtbot: object, tmp_path) -> None:
    """XW-6612-style plans: a page count typo must surface in the dialog,
    not only at print time."""
    pdf_path = tmp_path / "piece.pdf"
    doc = fitz.open()
    for _ in range(5):
        doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()
    config = AppConfig(
        printing=PrintingSection(
            print_profiles=[
                {"id": "noten_simplex", "label": "Noten Duplex", "printer_name": "Printer A"},
                {"id": "brochure_mono", "label": "Broschuere", "printer_name": "Printer B"},
            ]
        )
    )
    container = Container(config)
    piece = PieceBlock(
        sku="XW-6612",
        name="Luecke",
        qty_needed=1,
        print_plan=[
            {"range": "1-2", "profile_id": "noten_simplex"},
            # Row 2 skips page 3 (gap) and re-covers page 4 (overlap with a
            # hypothetical row that would have ended at 4) - here it simply
            # leaves a gap at page 3 relative to a full 1-5 plan.
            {"range": "4-5", "profile_id": "brochure_mono"},
        ],
        product=Product(id="p1", sku="XW-6612", name="Luecke", print_file_path=str(pdf_path)),
    )

    dialog = ProductPrintConfigDialog(None, container, piece)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    assert "Luecke bei Seite(n) 3" in dialog._plan_summary.text()  # noqa: SLF001


def test_print_plan_summary_confirms_full_coverage(qtbot: object, tmp_path) -> None:
    pdf_path = tmp_path / "piece.pdf"
    doc = fitz.open()
    for _ in range(5):
        doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()
    config = AppConfig(
        printing=PrintingSection(
            print_profiles=[
                {"id": "noten_simplex", "label": "Noten Duplex", "printer_name": "Printer A"},
                {"id": "brochure_mono", "label": "Broschuere", "printer_name": "Printer B"},
            ]
        )
    )
    container = Container(config)
    piece = PieceBlock(
        sku="XW-6612",
        name="Vollstaendig",
        qty_needed=1,
        print_plan=[
            {"range": "1-2", "profile_id": "noten_simplex"},
            {"range": "3-END", "profile_id": "brochure_mono"},
        ],
        product=Product(id="p1", sku="XW-6612", name="Vollstaendig", print_file_path=str(pdf_path)),
    )

    dialog = ProductPrintConfigDialog(None, container, piece)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    assert "Deckt alle 5 Seite(n) genau einmal ab" in dialog._plan_summary.text()  # noqa: SLF001


def test_print_dialog_shows_note_for_other_title_overrides(qtbot: object, tmp_path) -> None:
    pdf_path = tmp_path / "piece.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    class CatalogStub:
        def title_overrides_for_sku(self, sku: str) -> list[str]:
            assert sku == "XW-6612"
            return ["Andere Fassung", "Aktueller Titel"]

    container = Container(AppConfig())
    container.register(ProductCatalogService, lambda _c: CatalogStub())  # type: ignore[return-value]
    piece = PieceBlock(
        sku="XW-6612",
        name="Aktueller Titel",
        qty_needed=1,
        print_plan=[{"range": "Alle Seiten", "profile_id": "noten_duplex"}],
        product=Product(id="p1", sku="XW-6612", name="Aktueller Titel", print_file_path=str(pdf_path)),
    )

    dialog = ProductPrintConfigDialog(None, container, piece)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    note = dialog._title_override_note.text()  # noqa: SLF001
    assert not dialog._title_override_note.isHidden()  # noqa: SLF001
    assert "Andere Fassung" in note
    assert "Aktueller Titel" not in note


def test_print_dialog_hides_note_when_no_other_title_overrides_exist(qtbot: object, tmp_path) -> None:
    pdf_path = tmp_path / "piece.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    class CatalogStub:
        def title_overrides_for_sku(self, sku: str) -> list[str]:
            return []

    container = Container(AppConfig())
    container.register(ProductCatalogService, lambda _c: CatalogStub())  # type: ignore[return-value]
    piece = PieceBlock(
        sku="XW-6612",
        name="Einziger Titel",
        qty_needed=1,
        print_plan=[{"range": "Alle Seiten", "profile_id": "noten_duplex"}],
        product=Product(id="p1", sku="XW-6612", name="Einziger Titel", print_file_path=str(pdf_path)),
    )

    dialog = ProductPrintConfigDialog(None, container, piece)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    assert dialog._title_override_note.isHidden()  # noqa: SLF001


def test_print_plan_printer_selection_commits_immediately(qtbot: object, tmp_path) -> None:
    pdf_path = tmp_path / "piece.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()
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
        sku="XW-6014",
        name="Mnoschil",
        qty_needed=1,
        print_plan=[
            {"range": "1-8", "profile_id": "brochure_mono"},
            {"range": "9-END", "profile_id": "brochure_mono"},
        ],
        product=Product(id="p1", sku="XW-6014", name="Mnoschil", print_file_path=str(pdf_path)),
    )
    dialog = ProductPrintConfigDialog(None, container, piece)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    model = dialog._plan_model  # noqa: SLF001
    index = model.index(1, 1)
    delegate = dialog._plan_table.itemDelegateForColumn(1)  # noqa: SLF001
    editor = delegate.createEditor(dialog, QStyleOptionViewItem(), index)
    assert isinstance(editor, QComboBox)
    delegate.commitData.connect(
        lambda current_editor: delegate.setModelData(current_editor, model, index)
    )
    delegate.setEditorData(editor, index)

    editor.setCurrentIndex(editor.findData("noten_duplex"))

    assert model.plan() == [
        {"range": "1-8", "profile_id": "brochure_mono"},
        {"range": "9-END", "profile_id": "noten_duplex"},
    ]
