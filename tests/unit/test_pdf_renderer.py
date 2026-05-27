from __future__ import annotations

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

        def pageRect(self, _unit: object) -> QRect:
            return QRect(0, 0, 4960, 7016)

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

    pdf_renderer.print_pdf_with_qprinter(str(pdf_path), "Printer", dpi=600, center_on_page=False)

    assert calls["resolution"] == 600
    assert calls["draw_pos"] == QPointF(0.0, 0.0)
    assert calls["draw_image"] is not None
    assert calls["ended"] is True


def test_print_pdf_with_qprinter_does_not_configure_driver_options(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "a4.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    printer = MagicMock()
    printer.pageRect.return_value = QRect(0, 0, 4960, 7016)
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
    assert not printer.setFullPage.called
