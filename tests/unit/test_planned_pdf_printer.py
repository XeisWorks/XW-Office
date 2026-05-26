from __future__ import annotations

from unittest.mock import patch

from xw_studio.core.config import PrintingSection
from xw_studio.services.printing.planned_pdf_printer import (
    page_indices_from_range_text,
    print_pdf_by_plan,
    resolve_plan_targets,
)


def _printing_config() -> PrintingSection:
    return PrintingSection(
        print_profiles=[
            {
                "id": "noten_simplex",
                "label": "Noten A4 Simplex",
                "printer_name": "Simplex",
                "dpi": 600,
                "duplex": "simplex",
            },
            {
                "id": "noten_duplex",
                "label": "Noten A4 Duplex",
                "printer_name": "Duplex",
                "dpi": 600,
                "duplex": "long",
            },
            {
                "id": "brochure_mono",
                "label": "Canon Broschuere Mono",
                "printer_name": "Brochure",
                "dpi": 600,
                "duplex": "long",
            },
        ]
    )


def test_page_indices_from_range_text_supports_legacy_end_syntax() -> None:
    assert page_indices_from_range_text("1-2,END", page_count=5) == [0, 1, 4]
    assert page_indices_from_range_text("Alle Seiten", page_count=5) is None


def test_resolve_plan_targets_maps_legacy_profile_aliases() -> None:
    printing = _printing_config()

    targets = resolve_plan_targets(
        printing,
        print_plan=[{"range": "1-3", "profile_id": "noten_a4_duplex"}],
    )

    assert len(targets) == 1
    assert targets[0].printer_name == "Duplex"
    assert targets[0].range_text == "1-3"
    assert targets[0].duplex == "long"


def test_print_pdf_by_plan_dispatches_each_target_with_parsed_pages() -> None:
    printing = _printing_config()

    class _PrinterStub:
        class PrinterMode:
            HighResolution = object()

        def __init__(self, *_args, **_kwargs) -> None:
            self.printer_name = ""

        def setPrinterName(self, value: str) -> None:
            self.printer_name = value

    with patch("xw_studio.services.printing.planned_pdf_printer.QPrinter", _PrinterStub), patch(
        "xw_studio.services.printing.planned_pdf_printer.print_pdf"
    ) as mock_print:
        print_pdf_by_plan(
            "C:/tmp/test.pdf",
            printing,
            print_plan=[{"range": "2-END", "profile_id": "brochure_mono"}],
            page_count=4,
        )

    assert mock_print.call_count == 1
    assert mock_print.call_args.kwargs["pages"] == [1, 2, 3]
    assert mock_print.call_args.kwargs["dpi"] == 600
    assert mock_print.call_args.kwargs["duplex"] == "long"


def test_print_pdf_by_plan_uses_internal_renderer_without_shelling_out() -> None:
    printing = _printing_config()

    class _PrinterStub:
        class PrinterMode:
            HighResolution = object()

        def __init__(self, *_args, **_kwargs) -> None:
            self.printer_name = ""

        def setPrinterName(self, value: str) -> None:
            self.printer_name = value

    with patch("xw_studio.services.printing.planned_pdf_printer.QPrinter", _PrinterStub), patch(
        "xw_studio.services.printing.planned_pdf_printer.print_pdf"
    ) as mock_print, patch("subprocess.Popen") as mock_popen, patch("os.startfile", create=True) as mock_startfile:
        print_pdf_by_plan(
            "C:/tmp/test.pdf",
            printing,
            profile_id="noten_duplex",
            page_count=4,
        )

    mock_print.assert_called_once()
    mock_popen.assert_not_called()
    mock_startfile.assert_not_called()
