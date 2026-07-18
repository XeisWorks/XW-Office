from __future__ import annotations

import types
from unittest.mock import MagicMock

import fitz
from PySide6.QtCore import QPointF, QRect, QRectF

from xw_studio.services.printing import pdf_renderer


def test_print_pdf_with_qprinter_draws_image_without_scaling(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "a4.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    calls: dict[str, object] = {}
    events: list[str] = []

    class PrinterStub:
        class PrinterMode:
            HighResolution = object()

        class OutputFormat:
            NativeFormat = object()

        class Unit:
            DevicePixel = object()

        def __init__(self, *_args: object) -> None:
            self.name = ""

        def setOutputFormat(self, value: object) -> None:
            calls["output_format"] = value

        def setPrinterName(self, value: str) -> None:
            self.name = value

        def setPageSize(self, value: object) -> None:
            calls["page_size"] = value

        def setPageOrientation(self, value: object) -> None:
            calls["page_orientation"] = value

        def setResolution(self, value: int) -> None:
            calls["resolution"] = value

        def resolution(self) -> int:
            return int(calls.get("resolution", 600))

        def setFullPage(self, value: bool) -> None:
            events.append("setFullPage")
            calls["full_page"] = value

        def pageRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def paperRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def pageLayout(self) -> object:
            return object()

        def newPage(self) -> None:
            calls["new_page"] = True

    class PainterStub:
        def begin(self, printer: object) -> bool:
            events.append("begin")
            calls["begin_printer"] = printer
            return True

        def drawImage(self, pos: QPointF, image: object) -> None:
            calls["draw_pos"] = pos
            calls["draw_image"] = image

        def end(self) -> None:
            calls["ended"] = True

    monkeypatch.setattr(pdf_renderer, "QPrinter", PrinterStub)
    monkeypatch.setattr(pdf_renderer, "QPainter", PainterStub)
    pdf_renderer.print_pdf_with_qprinter(str(pdf_path), "Printer", dpi=600)

    assert calls["resolution"] == 600
    assert calls["full_page"] is True
    assert events.index("setFullPage") < events.index("begin")
    assert calls["draw_pos"] == QPointF(0.0, 0.0)
    assert calls["draw_image"] is not None
    assert calls["ended"] is True


def test_print_pdf_with_qprinter_uses_queue_resolution_without_overriding(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "a4.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    calls: dict[str, object] = {}
    events: list[str] = []

    class PrinterStub:
        class PrinterMode:
            HighResolution = object()

        class OutputFormat:
            NativeFormat = object()

        def __init__(self, *_args: object) -> None:
            pass

        def setOutputFormat(self, value: object) -> None:
            calls["output_format"] = value

        def setPrinterName(self, value: str) -> None:
            calls["printer_name"] = value

        def setPageSize(self, value: object) -> None:
            calls["page_size"] = value

        def setPageOrientation(self, value: object) -> None:
            calls["page_orientation"] = value

        def setResolution(self, value: int) -> None:
            calls["resolution"] = value

        def resolution(self) -> int:
            return 600

        def setFullPage(self, value: bool) -> None:
            events.append("setFullPage")
            calls["full_page"] = value

        def pageRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def paperRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def pageLayout(self) -> object:
            return object()

        def newPage(self) -> None:
            calls["new_page"] = True

    class PainterStub:
        def begin(self, printer: object) -> bool:
            events.append("begin")
            calls["begin_printer"] = printer
            return True

        def drawImage(self, pos: QPointF, image: object) -> None:
            calls["draw_pos"] = pos
            calls["draw_image"] = image

        def end(self) -> None:
            calls["ended"] = True

    monkeypatch.setattr(pdf_renderer, "QPrinter", PrinterStub)
    monkeypatch.setattr(pdf_renderer, "QPainter", PainterStub)

    pdf_renderer.print_pdf_with_qprinter(str(pdf_path), "Printer", dpi=None, fallback_dpi=300)

    assert "resolution" not in calls
    assert calls["full_page"] is True
    assert calls["draw_pos"] == QPointF(0.0, 0.0)
    assert calls["draw_image"] is not None


def test_print_pdf_with_qprinter_printable_origin_sets_full_page_false(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "a4.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    calls: dict[str, object] = {}
    events: list[str] = []

    class PrinterStub:
        class PrinterMode:
            HighResolution = object()

        class OutputFormat:
            NativeFormat = object()

        class Unit:
            DevicePixel = object()

        def __init__(self, *_args: object) -> None:
            pass

        def setOutputFormat(self, value: object) -> None:
            calls["output_format"] = value

        def setPrinterName(self, value: str) -> None:
            calls["printer_name"] = value

        def setPageSize(self, value: object) -> None:
            calls["page_size"] = value

        def setPageOrientation(self, value: object) -> None:
            calls["page_orientation"] = value

        def setFullPage(self, value: bool) -> None:
            events.append("setFullPage")
            calls["full_page"] = value

        def setResolution(self, value: int) -> None:
            calls["resolution"] = value

        def resolution(self) -> int:
            return 600

        def pageRect(self, _unit: object) -> QRect:
            return QRect(142, 100, 4674, 6816)

        def paperRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4958, 7016)

        def pageLayout(self) -> object:
            return object()

        def newPage(self) -> None:
            calls["new_page"] = True

    class PainterStub:
        def begin(self, printer: object) -> bool:
            events.append("begin")
            calls["begin_printer"] = printer
            return True

        def drawImage(self, pos: QPointF, image: object) -> None:
            calls["draw_pos"] = pos
            calls["draw_image"] = image

        def end(self) -> None:
            calls["ended"] = True

    monkeypatch.setattr(pdf_renderer, "QPrinter", PrinterStub)
    monkeypatch.setattr(pdf_renderer, "QPainter", PainterStub)

    pdf_renderer.print_pdf_with_qprinter(
        str(pdf_path),
        "Printer",
        dpi=None,
        placement_mode="printable_origin",
        x_offset_mm=-2.0,
        y_offset_mm=1.0,
    )

    assert calls["full_page"] is False
    assert events.index("setFullPage") < events.index("begin")
    assert calls["draw_pos"] == QPointF(pdf_renderer.mm_to_px(-2.0, 600), pdf_renderer.mm_to_px(1.0, 600))
    assert calls["draw_image"] is not None


def test_print_pdf_with_qprinter_configures_only_invoice_page_options(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "a4.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    printer = MagicMock()
    printer.pageRect.return_value = QRect(0, 0, 4960, 7016)
    printer.paperRect.return_value = QRect(0, 0, 4960, 7016)
    printer.resolution.return_value = 600
    printer.OutputFormat.NativeFormat = object()

    class PrinterFactory:
        class PrinterMode:
            HighResolution = object()

        class OutputFormat:
            NativeFormat = object()

        class Unit:
            DevicePixel = object()

        def __new__(cls, *_args: object) -> MagicMock:
            return printer

    class PainterStub:
        def begin(self, _printer: object) -> bool:
            return True

        def drawImage(self, _pos: object, _image: object) -> None:
            return None

        def end(self) -> None:
            return None

    monkeypatch.setattr(pdf_renderer, "QPrinter", PrinterFactory)
    monkeypatch.setattr(pdf_renderer, "QPainter", PainterStub)

    pdf_renderer.print_pdf_with_qprinter(str(pdf_path), "Printer", dpi=600)

    assert not printer.setPageLayout.called
    assert printer.setPageSize.called
    assert printer.setPageOrientation.called
    assert not printer.setOrientation.called
    assert not printer.setDuplex.called

    printer.reset_mock()
    pdf_renderer.print_pdf_with_qprinter(str(pdf_path), "Printer", dpi=600, job_kind="product")

    assert not printer.setPageLayout.called
    assert not printer.setPageSize.called
    assert not printer.setPageOrientation.called
    assert not printer.setOrientation.called
    assert not printer.setDuplex.called


def test_print_pdf_with_qprinter_sets_fallback_resolution_when_driver_dpi_invalid(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "a4.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    calls: dict[str, object] = {}

    class PrinterStub:
        class PrinterMode:
            HighResolution = object()

        class OutputFormat:
            NativeFormat = object()

        class Unit:
            DevicePixel = object()

        def __init__(self, *_args: object) -> None:
            pass

        def setOutputFormat(self, value: object) -> None:
            calls["output_format"] = value

        def setPrinterName(self, value: str) -> None:
            calls["printer_name"] = value

        def setPageSize(self, value: object) -> None:
            calls["page_size"] = value

        def setPageOrientation(self, value: object) -> None:
            calls["page_orientation"] = value

        def setFullPage(self, value: bool) -> None:
            calls["full_page"] = value

        def setResolution(self, value: int) -> None:
            calls["resolution"] = value

        def resolution(self) -> int:
            return int(calls.get("resolution", 0))

        def pageRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def paperRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def pageLayout(self) -> object:
            return object()

        def newPage(self) -> None:
            calls["new_page"] = True

    class PainterStub:
        def begin(self, printer: object) -> bool:
            calls["begin_printer"] = printer
            return True

        def drawImage(self, pos: QPointF, image: object) -> None:
            calls["draw_pos"] = pos
            calls["draw_image"] = image

        def end(self) -> None:
            calls["ended"] = True

    monkeypatch.setattr(pdf_renderer, "QPrinter", PrinterStub)
    monkeypatch.setattr(pdf_renderer, "QPainter", PainterStub)

    pdf_renderer.print_pdf_with_qprinter(str(pdf_path), "Printer", dpi=None, fallback_dpi=300)

    assert calls["resolution"] == 300


def test_print_pdf_with_qprinter_logs_print_metrics(monkeypatch, tmp_path, caplog) -> None:
    pdf_path = tmp_path / "a4.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for y in range(80, 220, 18):
        page.draw_line((80, y), (500, y), color=(0, 0, 0), width=0.8)
    page.insert_text((100, 260), "Notation", fontsize=24, color=(0, 0, 0))
    doc.save(pdf_path)
    doc.close()

    class PrinterStub:
        class PrinterMode:
            HighResolution = object()

        class OutputFormat:
            NativeFormat = object()

        class Unit:
            DevicePixel = object()

        def __init__(self, *_args: object) -> None:
            pass

        def setOutputFormat(self, _value: object) -> None:
            return None

        def setPrinterName(self, _value: str) -> None:
            return None

        def setFullPage(self, _value: bool) -> None:
            return None

        def setResolution(self, _value: int) -> None:
            return None

        def resolution(self) -> int:
            return 600

        def pageRect(self, _unit: object) -> QRect:
            return QRect(142, 100, 4674, 6816)

        def paperRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4958, 7016)

        def pageLayout(self) -> object:
            return object()

        def newPage(self) -> None:
            return None

    class PainterStub:
        def begin(self, _printer: object) -> bool:
            return True

        def drawImage(self, _pos: QPointF, _image: object) -> None:
            return None

        def end(self) -> None:
            return None

    monkeypatch.setattr(pdf_renderer, "QPrinter", PrinterStub)
    monkeypatch.setattr(pdf_renderer, "QPainter", PainterStub)
    monkeypatch.setattr(
        pdf_renderer,
        "classify_pdf_page_for_print",
        lambda _page: pdf_renderer.PagePrintAnalysis("notation", 0.9, 0.03, 0.04, 0.0, reason="test"),
    )

    with caplog.at_level("DEBUG", logger="xw_studio.services.printing.pdf_renderer"):
        pdf_renderer.print_pdf_with_qprinter(
            str(pdf_path),
            "Printer",
            dpi=None,
            placement_mode="calibrated",
            x_offset_mm=-1.5,
            y_offset_mm=0.5,
            job_kind="product",
        )

    assert "PDF print page metrics" in caplog.text
    assert "placement_mode=calibrated" in caplog.text
    assert "x_offset_mm=-1.500" in caplog.text
    assert "draw_target=" in caplog.text
    assert "effective_render_color_mode=gray" in caplog.text
    assert "effective_black_enhancement=adaptive_music" in caplog.text


def test_print_pdf_with_qprinter_respects_explicit_grayscale_enhancement(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class PixmapStub:
        width = 2
        height = 1
        stride = 2
        samples = bytes([255, 120])

    class PageStub:
        rect = types.SimpleNamespace(width=595.0, height=842.0)

        def get_pixmap(self, **kwargs: object) -> PixmapStub:
            calls["pixmap_kwargs"] = kwargs
            return PixmapStub()

    class DocStub:
        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> PageStub:
            assert index == 0
            return PageStub()

        def close(self) -> None:
            calls["closed"] = True

    class PrinterStub:
        class PrinterMode:
            HighResolution = object()

        class OutputFormat:
            NativeFormat = object()

        class Unit:
            DevicePixel = object()

        def __init__(self, *_args: object) -> None:
            pass

        def setOutputFormat(self, _value: object) -> None:
            return None

        def setPrinterName(self, _value: str) -> None:
            return None

        def setFullPage(self, _value: bool) -> None:
            return None

        def setResolution(self, _value: int) -> None:
            return None

        def resolution(self) -> int:
            return 600

        def pageRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def paperRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def pageLayout(self) -> object:
            return object()

        def newPage(self) -> None:
            return None

    class PainterStub:
        def begin(self, _printer: object) -> bool:
            return True

        def drawImage(self, pos: QPointF, image: object) -> None:
            calls["draw_pos"] = pos
            calls["draw_image"] = image

        def end(self) -> None:
            return None

    monkeypatch.setattr(pdf_renderer, "QPrinter", PrinterStub)
    monkeypatch.setattr(pdf_renderer, "QPainter", PainterStub)
    monkeypatch.setattr(pdf_renderer.fitz, "open", lambda _path: DocStub())

    pdf_renderer.print_pdf_with_qprinter(
        "fake.pdf",
        "Printer",
        job_kind="product",
        render_color_mode="gray",
        black_enhancement="adaptive_music",
    )

    assert calls["pixmap_kwargs"] == {"dpi": 600, "colorspace": fitz.csGRAY, "alpha": False}
    image = calls["draw_image"]
    assert isinstance(image, pdf_renderer.QImage)
    assert image.format() == pdf_renderer.QImage.Format.Format_Grayscale8
    assert calls["draw_pos"] == QPointF(0.0, 0.0)


def test_gray_black_enhancement_darkens_without_touching_white() -> None:
    enhanced = pdf_renderer._enhance_gray_samples(bytes([255, 250, 249, 120, 0]), "darken", 180)

    assert enhanced[0] == 255
    assert enhanced[1] == 255
    assert enhanced[2] < 249
    assert enhanced[3] < 120
    assert enhanced[4] == 0


def test_music_black_enhancement_makes_notation_pixels_much_darker() -> None:
    enhanced = pdf_renderer._enhance_gray_samples(bytes([255, 252, 251, 220, 180, 90, 0]), "music_black", 180)

    assert enhanced[0] == 255
    assert enhanced[1] == 255
    assert enhanced[2] < 160
    assert enhanced[3] < 90
    assert enhanced[4] == 0
    assert enhanced[5] == 0
    assert enhanced[6] == 0


def test_adaptive_music_enhancement_keeps_white_and_darkens_notes() -> None:
    enhanced = pdf_renderer._enhance_gray_samples(bytes([255, 248, 220, 160, 120, 60, 0]), "adaptive_music", 180)

    assert enhanced[0] == 255
    assert enhanced[1] == 255
    assert enhanced[2] < 150
    assert enhanced[3] < 70
    assert enhanced[4] < 10
    assert enhanced[5] == 0
    assert enhanced[6] == 0


def test_classify_notation_page_without_cover_assumption() -> None:
    class PixmapStub:
        width = 100
        height = 100
        samples = (bytes([255, 255, 255]) * 9300) + (bytes([0, 0, 0]) * 500) + (bytes([230, 230, 230]) * 200)

    class PageStub:
        def get_pixmap(self, **kwargs: object) -> PixmapStub:
            assert kwargs["dpi"] == 72
            assert kwargs["colorspace"] == fitz.csRGB
            return PixmapStub()

    analysis = pdf_renderer.classify_pdf_page_for_print(PageStub())  # type: ignore[arg-type]

    assert analysis.page_class == "notation"


def test_classify_antialiased_notation_page_as_notation() -> None:
    class PixmapStub:
        width = 100
        height = 100
        samples = (bytes([255, 255, 255]) * 8500) + (bytes([0, 0, 0]) * 200) + (bytes([205, 205, 205]) * 1300)

    class PageStub:
        def get_pixmap(self, **_kwargs: object) -> PixmapStub:
            return PixmapStub()

    analysis = pdf_renderer.classify_pdf_page_for_print(PageStub())  # type: ignore[arg-type]

    assert analysis.page_class == "notation"


def test_classify_dense_notation_page_as_notation() -> None:
    class PixmapStub:
        width = 100
        height = 100
        samples = (bytes([255, 255, 255]) * 7900) + (bytes([0, 0, 0]) * 350) + (bytes([205, 205, 205]) * 1750)

    class PageStub:
        def get_pixmap(self, **_kwargs: object) -> PixmapStub:
            return PixmapStub()

    analysis = pdf_renderer.classify_pdf_page_for_print(PageStub())  # type: ignore[arg-type]

    assert analysis.page_class == "notation"


def test_classify_sparse_notation_page_as_notation() -> None:
    class PixmapStub:
        width = 100
        height = 100
        samples = (bytes([255, 255, 255]) * 9880) + (bytes([0, 0, 0]) * 10) + (bytes([230, 230, 230]) * 110)

    class PageStub:
        def get_pixmap(self, **_kwargs: object) -> PixmapStub:
            return PixmapStub()

    analysis = pdf_renderer.classify_pdf_page_for_print(PageStub())  # type: ignore[arg-type]

    assert analysis.page_class == "notation"


def test_classify_graphic_page_from_midtones_and_color() -> None:
    class PixmapStub:
        width = 100
        height = 100
        samples = (bytes([160, 160, 160]) * 5000) + (bytes([180, 130, 90]) * 3000) + (bytes([255, 255, 255]) * 2000)

    class PageStub:
        def get_pixmap(self, **_kwargs: object) -> PixmapStub:
            return PixmapStub()

    analysis = pdf_renderer.classify_pdf_page_for_print(PageStub())  # type: ignore[arg-type]

    assert analysis.page_class == "graphic"


def test_classify_shadow_cover_is_not_notation() -> None:
    class PixmapStub:
        width = 100
        height = 100
        samples = (
            (bytes([255, 255, 255]) * 8500)
            + (bytes([170, 170, 170]) * 1000)
            + (bytes([40, 40, 40]) * 400)
            + (bytes([80, 150, 50]) * 100)
        )

    class PageStub:
        def get_pixmap(self, **_kwargs: object) -> PixmapStub:
            return PixmapStub()

    analysis = pdf_renderer.classify_pdf_page_for_print(PageStub())  # type: ignore[arg-type]

    assert analysis.page_class != "notation"


def test_auto_render_strategy_protects_graphic_and_mixed_pages() -> None:
    notation = pdf_renderer.PagePrintAnalysis("notation", 0.9, 0.03, 0.04, 0.0)
    graphic = pdf_renderer.PagePrintAnalysis("graphic", 0.4, 0.1, 0.4, 0.1)
    mixed = pdf_renderer.PagePrintAnalysis("mixed", 0.73, 0.02, 0.14, 0.0)

    assert pdf_renderer._resolve_page_render_strategy(
        job_kind="product",
        requested_render_color_mode="auto",
        requested_black_enhancement="auto_music",
        analysis=notation,
    ).black_enhancement == "adaptive_music"
    assert pdf_renderer._resolve_page_render_strategy(
        job_kind="product",
        requested_render_color_mode="auto",
        requested_black_enhancement="auto_music",
        analysis=graphic,
    ).black_enhancement == "none"
    assert pdf_renderer._resolve_page_render_strategy(
        job_kind="product",
        requested_render_color_mode="auto",
        requested_black_enhancement="auto_music",
        analysis=mixed,
    ).black_enhancement == "none"


def test_explicit_music_black_and_none_overrides_are_respected() -> None:
    analysis = pdf_renderer.PagePrintAnalysis("graphic", 0.4, 0.1, 0.4, 0.1)

    assert pdf_renderer._resolve_page_render_strategy(
        job_kind="product",
        requested_render_color_mode="gray",
        requested_black_enhancement="music_black",
        analysis=analysis,
    ).black_enhancement == "music_black"
    assert pdf_renderer._resolve_page_render_strategy(
        job_kind="product",
        requested_render_color_mode="rgb",
        requested_black_enhancement="none",
        analysis=analysis,
    ).render_color_mode == "rgb"


def test_auto_page_analysis_is_cached_across_copies(monkeypatch) -> None:
    calls: dict[str, object] = {"analysis": 0, "draws": 0}

    class PixmapStub:
        width = 1
        height = 1
        stride = 1
        samples = bytes([0])

    class PageStub:
        rect = types.SimpleNamespace(width=595.0, height=842.0)

        def get_pixmap(self, **_kwargs: object) -> PixmapStub:
            return PixmapStub()

    class DocStub:
        def __len__(self) -> int:
            return 2

        def __getitem__(self, index: int) -> PageStub:
            assert index in {0, 1}
            return PageStub()

        def close(self) -> None:
            return None

    class PrinterStub:
        class PrinterMode:
            HighResolution = object()

        class OutputFormat:
            NativeFormat = object()

        class Unit:
            DevicePixel = object()

        def __init__(self, *_args: object) -> None:
            pass

        def setOutputFormat(self, _value: object) -> None:
            return None

        def setPrinterName(self, _value: str) -> None:
            return None

        def setFullPage(self, _value: bool) -> None:
            return None

        def resolution(self) -> int:
            return 600

        def pageRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def paperRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

        def pageLayout(self) -> object:
            return object()

        def newPage(self) -> None:
            return None

    class PainterStub:
        def begin(self, _printer: object) -> bool:
            return True

        def drawImage(self, _pos: QPointF, _image: object) -> None:
            calls["draws"] = int(calls["draws"]) + 1

        def end(self) -> None:
            return None

    def fake_analysis(_page: object, *, sample_dpi: int = 72) -> pdf_renderer.PagePrintAnalysis:
        assert sample_dpi == 72
        calls["analysis"] = int(calls["analysis"]) + 1
        return pdf_renderer.PagePrintAnalysis("notation", 0.9, 0.03, 0.04, 0.0)

    monkeypatch.setattr(pdf_renderer, "QPrinter", PrinterStub)
    monkeypatch.setattr(pdf_renderer, "QPainter", PainterStub)
    monkeypatch.setattr(pdf_renderer.fitz, "open", lambda _path: DocStub())
    monkeypatch.setattr(pdf_renderer, "classify_pdf_page_for_print", fake_analysis)

    pdf_renderer.print_pdf_with_qprinter("fake.pdf", "Printer", job_kind="product", copies=2)

    assert calls["analysis"] == 2
    assert calls["draws"] == 4


def test_create_calibration_pdf_contains_one_page(tmp_path) -> None:
    path = tmp_path / "calibration.pdf"

    created = pdf_renderer.create_calibration_pdf(
        path,
        printer_name="Printer",
        placement_mode="calibrated",
        x_offset_mm=-2.0,
        y_offset_mm=0.0,
    )

    doc = fitz.open(created)
    try:
        assert len(doc) == 1
    finally:
        doc.close()


def test_fit_center_target_rect_uses_printable_area(monkeypatch) -> None:
    image = pdf_renderer.QImage(100, 200, pdf_renderer.QImage.Format.Format_RGB888)

    class LayoutStub:
        def fullRectPixels(self, _dpi: int) -> QRect:
            return QRect(0, 0, 1200, 1200)

        def paintRectPixels(self, _dpi: int) -> QRect:
            return QRect(100, 50, 1000, 1000)

    class PrinterStub:
        def pageLayout(self) -> LayoutStub:
            return LayoutStub()

    target = pdf_renderer._target_rect(
        printer=PrinterStub(),  # type: ignore[arg-type]
        image=image,
        dpi=100,
        scale_mode="fit",
        alignment="center",
        x_offset_mm=0.0,
        y_offset_mm=0.0,
    )

    assert isinstance(target, QRectF)
    assert target == QRectF(350.0, 50.0, 500.0, 1000.0)
