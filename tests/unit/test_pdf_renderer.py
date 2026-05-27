from __future__ import annotations

import types
from unittest.mock import MagicMock

import fitz
from PySide6.QtCore import QPointF, QRect

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


def test_print_pdf_with_qprinter_does_not_configure_driver_options(monkeypatch, tmp_path) -> None:
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
    assert not printer.setPageSize.called
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
    doc.new_page(width=595, height=842)
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

    with caplog.at_level("INFO", logger="xw_studio.services.printing.pdf_renderer"):
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
    assert "draw_px=(" in caplog.text
    assert "render_color_mode=gray" in caplog.text
    assert "black_enhancement=music_black" in caplog.text


def test_print_pdf_with_qprinter_renders_product_as_enhanced_grayscale(monkeypatch) -> None:
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

    pdf_renderer.print_pdf_with_qprinter("fake.pdf", "Printer", job_kind="product")

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
