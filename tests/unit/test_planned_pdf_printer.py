from __future__ import annotations

from unittest.mock import patch

import pytest

from xw_studio.core.config import PrintingSection
from xw_studio.services.printing.print_jobs import PdfPrintJob
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
            },
            {
                "id": "noten_duplex",
                "label": "Noten A4 Duplex",
                "printer_name": "Duplex",
                "dpi": 600,
            },
            {
                "id": "brochure_mono",
                "label": "Canon Broschuere Mono",
                "printer_name": "Brochure",
                "dpi": 600,
                "placement_mode": "calibrated",
                "page_size": "A5",
                "orientation": "portrait",
                "scale_mode": "fit",
                "alignment": "center",
                "x_offset_mm": -2.0,
                "y_offset_mm": 0.5,
                "render_color_mode": "gray",
                "black_enhancement": "threshold",
                "black_threshold": 200,
                "backend": "pdf_xchange",
                "native_pdf_exe": "C:/Program Files/PDFXEdit.exe",
            },
        ]
    )


def test_page_indices_from_range_text_supports_legacy_end_syntax() -> None:
    assert page_indices_from_range_text("1-2,END", page_count=5) == [0, 1, 4]
    assert page_indices_from_range_text("START-2,END", page_count=5) == [0, 1, 4]
    assert page_indices_from_range_text("START-END", page_count=3) == [0, 1, 2]
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


class _QueueStub:
    def __init__(self) -> None:
        self.jobs: list[PdfPrintJob] = []

    def enqueue(self, job: PdfPrintJob) -> str:
        self.jobs.append(job)
        return job.id


def test_print_pdf_by_plan_queues_target_with_parsed_pages_and_copies() -> None:
    printing = _printing_config()
    queue = _QueueStub()

    print_pdf_by_plan(
        "C:/tmp/test.pdf",
        printing,
        print_plan=[{"range": "2-END", "profile_id": "brochure_mono"}],
        page_count=4,
        copies=3,
        print_queue=queue,  # type: ignore[arg-type]
    )

    assert len(queue.jobs) == 1
    assert queue.jobs[0].pages == [1, 2, 3]
    assert queue.jobs[0].dpi == 600
    assert queue.jobs[0].copies == 3
    assert queue.jobs[0].printer_name == "Brochure"
    assert queue.jobs[0].placement_mode == "calibrated"
    assert queue.jobs[0].page_size == "A5"
    assert queue.jobs[0].orientation == "portrait"
    assert queue.jobs[0].scale_mode == "fit"
    assert queue.jobs[0].alignment == "center"
    assert queue.jobs[0].x_offset_mm == -2.0
    assert queue.jobs[0].y_offset_mm == 0.5
    assert queue.jobs[0].render_color_mode == "gray"
    assert queue.jobs[0].black_enhancement == "threshold"
    assert queue.jobs[0].black_threshold == 200
    assert queue.jobs[0].backend == "pdf_xchange"
    assert queue.jobs[0].native_pdf_exe == "C:/Program Files/PDFXEdit.exe"


def test_print_pdf_by_plan_uses_queue_without_shelling_out() -> None:
    printing = _printing_config()
    queue = _QueueStub()

    with patch("subprocess.Popen") as mock_popen, patch("os.startfile", create=True) as mock_startfile:
        print_pdf_by_plan(
            "C:/tmp/test.pdf",
            printing,
            profile_id="noten_duplex",
            page_count=4,
            print_queue=queue,  # type: ignore[arg-type]
        )

    assert len(queue.jobs) == 1
    mock_popen.assert_not_called()
    mock_startfile.assert_not_called()


def test_minimal_profile_keeps_dpi_optional() -> None:
    target = resolve_plan_targets(_printing_config(), profile_id="noten_simplex")[0]

    assert target.printer_name == "Simplex"
    assert target.dpi is None
    assert target.placement_mode == "paper_origin"
    assert target.page_size == ""
    assert target.orientation == ""
    assert target.scale_mode == "none"
    assert target.alignment == "top_left"
    assert target.x_offset_mm == 0.0
    assert target.y_offset_mm == 0.0
    assert target.render_color_mode == "auto"
    assert target.black_enhancement == "auto"
    assert target.black_threshold == 180
    assert target.backend == "qt_raster"
    assert target.native_pdf_exe == ""


def test_unknown_backend_is_rejected_during_plan_resolution() -> None:
    printing = PrintingSection(
        print_profiles=[{"id": "broken", "printer_name": "P", "backend": "magic"}]
    )

    with pytest.raises(RuntimeError, match="Unbekanntes PDF-Druckbackend"):
        resolve_plan_targets(printing, profile_id="broken")
