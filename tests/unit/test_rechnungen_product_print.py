from __future__ import annotations

from pathlib import Path
from threading import Event
import time

import fitz
from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtWidgets import QComboBox, QStyleOptionViewItem

from xw_office.core.config import AppConfig, PrintingSection
from xw_office.core.container import Container
from xw_office.core.types import PrinterStatus
from xw_office.services.inventory import InventoryService
from xw_office.services.products.catalog import Product
from xw_office.services.products.catalog import ProductCatalogService
from xw_office.services.products.print_decision import PieceBlock
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.printer_status.service import PrinterStatusService, PrinterStatusSnapshot
from xw_office.ui.modules.rechnungen import print_dialog
from xw_office.ui.modules.rechnungen.print_dialog import ProductPrintConfigDialog, prepare_piece_pdf_print
from xw_office.ui.modules.rechnungen.view import _PieceDelegate


def _wait_for_pdf_inspection(qtbot: object, dialog: ProductPrintConfigDialog) -> None:
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: dialog._pdf_validation_generation == dialog._pdf_generation, timeout=5000  # noqa: SLF001
    )


def test_product_print_runtime_check_uses_nonblocking_printer_snapshot(monkeypatch) -> None:
    container = Container(AppConfig())
    snapshot = PrinterStatusSnapshot(
        status=PrinterStatus.RED,
        printing_allowed=False,
        color="red",
        tooltip="Drucker nicht verfuegbar",
    )

    class StatusService:
        def snapshot(self) -> PrinterStatusSnapshot:
            return snapshot

    container.register(PrinterStatusService, lambda _container: StatusService())  # type: ignore[arg-type]
    warnings: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )

    assert not print_dialog._check_printer_runtime(None, container)  # type: ignore[arg-type]
    assert len(warnings) == 1
    assert "Kein konfigurierter Drucker" in str(warnings[0][2])


def test_product_print_config_title_override_read_runs_off_ui_thread(qtbot: object) -> None:
    entered, release = Event(), Event()

    class CatalogStub:
        def title_overrides_for_sku(self, _sku: str) -> list[str]:
            entered.set()
            assert release.wait(3)
            return ["Work A", "Work B"]

    container = Container(AppConfig())
    container.register(ProductCatalogService, lambda _: CatalogStub())  # type: ignore[arg-type,return-value]
    piece = PieceBlock(
        sku="XW-010",
        name="Work A",
        qty_needed=1,
        product=Product(id="p1", sku="XW-010", name="Work A"),
    )
    dialog = ProductPrintConfigDialog(None, container, piece)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    beats: list[bool] = []
    QTimer.singleShot(10, lambda: beats.append(True))
    try:
        qtbot.waitUntil(entered.is_set, timeout=1000)  # type: ignore[attr-defined]
        qtbot.waitUntil(lambda: bool(beats), timeout=1000)  # type: ignore[attr-defined]
        assert dialog._title_override_note.isHidden()  # noqa: SLF001
    finally:
        release.set()
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: dialog._title_override_worker is None, timeout=1000  # noqa: SLF001
    )
    assert not dialog._title_override_note.isHidden()  # noqa: SLF001


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

    rects = _PieceDelegate._button_rects(row, has_print_config=True)
    assert rects["qty_minus"].height() == 26
    assert rects["qty_minus"].width() == 22
    assert rects["qty_minus"].top() == 6
    assert rects["print"].height() == 26


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
    opened_paths: list[str] = []
    original_open = fitz.open

    def tracked_open(filename: str):
        opened_paths.append(str(filename))
        return original_open(filename)

    monkeypatch.setattr(print_dialog.fitz, "open", tracked_open)

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
    assert opened_paths == []
    job()
    assert opened_paths == [str(pdf_path)]
    assert captured == {
        "pdf_path": str(pdf_path),
        "profile_id": "noten_duplex",
        "copies": 7,
        "page_count": 1,
        "print_queue": queue,
        "job_kind": "product",
    }


def test_invalid_pdf_is_reported_by_worker_job_before_queue_submission(monkeypatch, tmp_path) -> None:
    missing_pdf = tmp_path / "missing.pdf"
    piece = PieceBlock(
        sku="XW-443",
        name="Missing PDF",
        qty_needed=1,
        print_profile_id="noten_duplex",
        product=Product(
            id="p1",
            sku="XW-443",
            name="Missing PDF",
            print_file_path=str(missing_pdf),
        ),
    )
    container = Container(AppConfig())
    container.register(PrintQueueService, lambda _container: object())  # type: ignore[return-value]
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog._check_printer_runtime",
        lambda *_args: True,
    )
    queued: list[bool] = []
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog.print_pdf_by_plan",
        lambda *_args, **_kwargs: queued.append(True),
    )

    job = prepare_piece_pdf_print(None, container, piece=piece)  # type: ignore[arg-type]

    assert job is not None
    try:
        job()
    except print_dialog.ProductPdfPreparationError:
        pass
    else:
        raise AssertionError("invalid PDF should fail during worker job preparation")
    assert queued == []


def test_prepare_piece_pdf_print_prompts_for_missing_print_config(monkeypatch, qtbot, tmp_path) -> None:
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
    save_attempts = 0

    class InventoryStub:
        def save_product_print_config(self, **kwargs: object) -> object:
            nonlocal save_attempts
            save_attempts += 1
            if save_attempts == 1:
                raise RuntimeError("transient settings failure")
            time.sleep(0.04)
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

    heartbeats: list[int] = []
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: heartbeats.append(1))
    heartbeat.start(1)

    try:
        failed_job = prepare_piece_pdf_print(None, container, piece=piece, copies=2)  # type: ignore[arg-type]
        job = prepare_piece_pdf_print(None, container, piece=piece, copies=2)  # type: ignore[arg-type]
    finally:
        heartbeat.stop()

    assert failed_job is None
    assert job is not None
    assert heartbeats, "Qt event loop must remain responsive while the settings commit runs"
    assert save_attempts == 2
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
                    "id": "noten_simplex_color",
                    "label": "Noten A4 Simplex Color",
                    "printer_name": "Noten A4 Simplex Color",
                    "backend": "pdf_xchange",
                },
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
    _wait_for_pdf_inspection(qtbot, dialog)

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
    assert "noten_simplex_color" in profile_ids


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
    _wait_for_pdf_inspection(qtbot, dialog)

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
    _wait_for_pdf_inspection(qtbot, dialog)

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
    _wait_for_pdf_inspection(qtbot, dialog)

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
    _wait_for_pdf_inspection(qtbot, dialog)

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
    _wait_for_pdf_inspection(qtbot, dialog)
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


def test_product_pdf_inspection_keeps_dialog_responsive(qtbot: object, tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "slow.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf_path)
    document.close()
    entered = Event()
    release = Event()
    real_open = fitz.open

    def slow_open(path: str):
        entered.set()
        assert release.wait(timeout=5)
        return real_open(path)

    monkeypatch.setattr(print_dialog.fitz, "open", slow_open)
    dialog = ProductPrintConfigDialog(
        None,
        Container(AppConfig()),
        PieceBlock(
            sku="XW-SLOW",
            name="Langsames PDF",
            qty_needed=1,
            print_profile_id="noten_duplex",
            product=Product(
                id="slow",
                sku="XW-SLOW",
                name="Langsames PDF",
                print_file_path=str(pdf_path),
            ),
        ),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    qtbot.waitUntil(entered.is_set, timeout=3000)  # type: ignore[attr-defined]
    heartbeats: list[int] = []
    timer = QTimer(dialog)
    timer.timeout.connect(lambda: heartbeats.append(1))
    timer.start(10)
    qtbot.waitUntil(lambda: bool(heartbeats), timeout=1000)  # type: ignore[attr-defined]
    release.set()
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: dialog._pdf_validation_generation == dialog._pdf_generation, timeout=3000  # noqa: SLF001
    )

    assert dialog._page_count == 1  # noqa: SLF001
    assert heartbeats


def test_product_pdf_open_path_metadata_check_keeps_dialog_responsive(
    qtbot: object, tmp_path, monkeypatch
) -> None:
    pdf_path = tmp_path / "slow-open.pdf"
    pdf_path.write_bytes(b"pdf")
    entered = Event()
    release = Event()
    dialog = ProductPrintConfigDialog(
        None,
        Container(AppConfig()),
        PieceBlock(
            sku="XW-OPEN",
            name="Langsamer Pfad",
            qty_needed=1,
            product=Product(
                id="open",
                sku="XW-OPEN",
                name="Langsamer Pfad",
                print_file_path=str(pdf_path),
            ),
        ),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _wait_for_pdf_inspection(qtbot, dialog)

    original_is_file = type(pdf_path).is_file

    def slow_is_file(path) -> bool:
        if path == pdf_path:
            entered.set()
            assert release.wait(timeout=5)
        return original_is_file(path)

    monkeypatch.setattr(type(pdf_path), "is_file", slow_is_file)
    opened: list[str] = []
    monkeypatch.setattr(
        print_dialog.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    dialog._open_pdf()  # noqa: SLF001
    qtbot.waitUntil(entered.is_set, timeout=3000)  # type: ignore[attr-defined]
    heartbeats: list[int] = []
    timer = QTimer(dialog)
    timer.timeout.connect(lambda: heartbeats.append(1))
    timer.start(10)
    qtbot.waitUntil(lambda: bool(heartbeats), timeout=1000)  # type: ignore[attr-defined]
    release.set()
    qtbot.waitUntil(lambda: dialog._path_action_worker is None, timeout=3000)  # type: ignore[attr-defined]

    assert heartbeats
    assert len(opened) == 1
    assert Path(opened[0]) == pdf_path


def test_product_pdf_folder_exists_check_runs_in_worker(qtbot: object, tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "folder-check.pdf"
    pdf_path.write_bytes(b"pdf")
    entered = Event()
    release = Event()
    dialog = ProductPrintConfigDialog(
        None,
        Container(AppConfig()),
        PieceBlock(
            sku="XW-FOLDER",
            name="Ordnerpruefung",
            qty_needed=1,
            product=Product(
                id="folder",
                sku="XW-FOLDER",
                name="Ordnerpruefung",
                print_file_path=str(pdf_path),
            ),
        ),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _wait_for_pdf_inspection(qtbot, dialog)

    original_exists = type(pdf_path).exists

    def slow_exists(path) -> bool:
        if path == tmp_path:
            entered.set()
            assert release.wait(timeout=5)
        return original_exists(path)

    monkeypatch.setattr(type(pdf_path), "exists", slow_exists)
    opened: list[str] = []
    monkeypatch.setattr(
        print_dialog.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    dialog._open_pdf_folder()  # noqa: SLF001
    qtbot.waitUntil(entered.is_set, timeout=3000)  # type: ignore[attr-defined]
    release.set()
    qtbot.waitUntil(lambda: dialog._path_action_worker is None, timeout=3000)  # type: ignore[attr-defined]

    assert len(opened) == 1
    assert Path(opened[0]) == tmp_path


def test_manual_pdf_inspection_and_queue_keep_ui_responsive(qtbot: object, tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "manual.pdf"
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.save(pdf_path)
    document.close()
    entered = Event()
    release = Event()
    real_open = fitz.open

    def slow_open(path: str):
        entered.set()
        assert release.wait(timeout=5)
        return real_open(path)

    monkeypatch.setattr(print_dialog.fitz, "open", slow_open)
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog._check_printer_runtime",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        print_dialog.QFileDialog,
        "getOpenFileName",
        lambda *_args: (str(pdf_path), "PDF (*.pdf)"),
    )

    class FakePrinter:
        class PrinterMode:
            HighResolution = object()

        class PrintRange:
            PageRange = "page-range"

        def __init__(self, _mode: object) -> None:
            self._name = ""

        def setPrinterName(self, name: str) -> None:
            self._name = name

        def printerName(self) -> str:
            return self._name

        def printRange(self) -> str:
            return self.PrintRange.PageRange

        def fromPage(self) -> int:
            return 2

        def toPage(self) -> int:
            return 2

    class FakePrinterInfo:
        @staticmethod
        def defaultPrinter() -> FakePrinterInfo:
            return FakePrinterInfo()

        @staticmethod
        def printerName() -> str:
            return "Test Printer"

    class FakePrintDialog:
        class DialogCode:
            Accepted = print_dialog.QDialog.DialogCode.Accepted

        def __init__(self, _printer: object, _parent: object) -> None:
            pass

        @staticmethod
        def exec() -> int:
            return print_dialog.QDialog.DialogCode.Accepted

    monkeypatch.setattr(print_dialog, "QPrinter", FakePrinter)
    monkeypatch.setattr(print_dialog, "QPrinterInfo", FakePrinterInfo)
    monkeypatch.setattr(print_dialog, "QPrintDialog", FakePrintDialog)

    queued: list[object] = []

    class PrintQueue:
        def enqueue(self, job: object) -> str:
            queued.append(job)
            return "manual-job-1"

    container = Container(AppConfig())
    container.register(PrintQueueService, lambda _container: PrintQueue())  # type: ignore[arg-type]
    parent = QComboBox()
    qtbot.addWidget(parent)  # type: ignore[attr-defined]
    print_dialog.run_invoice_pdf_print(parent, container)
    qtbot.waitUntil(entered.is_set, timeout=3000)  # type: ignore[attr-defined]
    heartbeats: list[int] = []
    timer = QTimer(parent)
    timer.timeout.connect(lambda: heartbeats.append(1))
    timer.start(10)
    qtbot.waitUntil(lambda: bool(heartbeats), timeout=1000)  # type: ignore[attr-defined]
    release.set()
    qtbot.waitUntil(lambda: len(queued) == 1, timeout=3000)  # type: ignore[attr-defined]

    assert heartbeats
    assert queued[0].pages == [1]


def test_product_pdf_inspection_discards_stale_path_result(qtbot: object, tmp_path, monkeypatch) -> None:
    first_path = tmp_path / "first.pdf"
    first_document = fitz.open()
    first_document.new_page()
    first_document.save(first_path)
    first_document.close()
    latest_path = tmp_path / "latest.pdf"
    latest_document = fitz.open()
    latest_document.new_page()
    latest_document.new_page()
    latest_document.save(latest_path)
    latest_document.close()
    first_entered = Event()
    release_first = Event()
    real_open = fitz.open

    def delayed_first_open(path: str):
        if str(path) == str(first_path):
            first_entered.set()
            assert release_first.wait(timeout=5)
        return real_open(path)

    monkeypatch.setattr(print_dialog.fitz, "open", delayed_first_open)
    dialog = ProductPrintConfigDialog(
        None,
        Container(AppConfig()),
        PieceBlock(
            sku="XW-SWITCH",
            name="Pfadwechsel",
            qty_needed=1,
            product=Product(
                id="switch",
                sku="XW-SWITCH",
                name="Pfadwechsel",
                print_file_path=str(first_path),
            ),
        ),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    qtbot.waitUntil(first_entered.is_set, timeout=3000)  # type: ignore[attr-defined]

    dialog._path_edit.setText(str(latest_path))  # noqa: SLF001
    release_first.set()
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: dialog._pdf_validation_path == str(latest_path), timeout=4000  # noqa: SLF001
    )

    assert dialog._page_count == 2  # noqa: SLF001
    assert "latest.pdf" in dialog._pdf_status.text()  # noqa: SLF001


def test_product_pdf_inspection_resumes_pending_save_after_validation(qtbot: object, tmp_path) -> None:
    pdf_path = tmp_path / "save-after-check.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf_path)
    document.close()
    dialog = ProductPrintConfigDialog(
        None,
        Container(AppConfig()),
        PieceBlock(
            sku="XW-SAVE",
            name="Speichern nach Pruefung",
            qty_needed=1,
            print_profile_id="noten_duplex",
            product=Product(
                id="save",
                sku="XW-SAVE",
                name="Speichern nach Pruefung",
                print_file_path=str(pdf_path),
            ),
        ),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    dialog.accept()
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: dialog.result() == dialog.DialogCode.Accepted, timeout=3000
    )

    assert dialog._page_count == 1  # noqa: SLF001


def test_product_pdf_inspection_ignores_result_after_dialog_close(qtbot: object, tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "close-during-check.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf_path)
    document.close()
    entered = Event()
    release = Event()
    real_open = fitz.open

    def delayed_open(path: str):
        entered.set()
        assert release.wait(timeout=5)
        return real_open(path)

    monkeypatch.setattr(print_dialog.fitz, "open", delayed_open)
    dialog = ProductPrintConfigDialog(
        None,
        Container(AppConfig()),
        PieceBlock(
            sku="XW-CLOSE",
            name="Schliessen waehrend PDF-Pruefung",
            qty_needed=1,
            product=Product(
                id="close",
                sku="XW-CLOSE",
                name="Schliessen waehrend PDF-Pruefung",
                print_file_path=str(pdf_path),
            ),
        ),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    qtbot.waitUntil(entered.is_set, timeout=3000)  # type: ignore[attr-defined]
    worker = dialog._pdf_status_worker  # noqa: SLF001
    assert worker is not None

    dialog.close()
    release.set()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=3000)  # type: ignore[attr-defined]

    assert dialog._page_count is None  # noqa: SLF001
