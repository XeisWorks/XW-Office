from __future__ import annotations

from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter

from xw_studio.services.printing.pdf_renderer import _configure_printer_for_a4_portrait, _duplex_mode


class _PrinterStub:
    def __init__(self) -> None:
        self.resolution = 0
        self.layout: QPageLayout | None = None
        self.full_page = False
        self.duplex: QPrinter.DuplexMode | None = None

    def setResolution(self, value: int) -> None:
        self.resolution = value

    def setPageLayout(self, value: QPageLayout) -> None:
        self.layout = value

    def setFullPage(self, value: bool) -> None:
        self.full_page = value

    def setDuplex(self, value: QPrinter.DuplexMode) -> None:
        self.duplex = value


def test_duplex_mode_maps_profile_values() -> None:
    assert _duplex_mode("simplex") == QPrinter.DuplexMode.DuplexNone
    assert _duplex_mode("long") == QPrinter.DuplexMode.DuplexLongSide
    assert _duplex_mode("short") == QPrinter.DuplexMode.DuplexShortSide
    assert _duplex_mode("") is None


def test_configure_printer_for_a4_portrait_sets_physical_layout_before_painting() -> None:
    printer = _PrinterStub()

    _configure_printer_for_a4_portrait(printer, dpi=600, duplex="long")  # type: ignore[arg-type]

    assert printer.resolution == 600
    assert printer.full_page is True
    assert printer.duplex == QPrinter.DuplexMode.DuplexLongSide
    assert printer.layout is not None
    assert printer.layout.orientation() == QPageLayout.Orientation.Portrait
    assert printer.layout.pageSize().id() == QPageSize.PageSizeId.A4
