from __future__ import annotations

from unittest.mock import patch

import pytest

from xw_office.core.config import PrintingSection
from xw_office.services.printing.print_jobs import PdfPrintJob, PrintJobResult
from xw_office.services.printing.planned_pdf_printer import (
    PrintPlanPartialFailure,
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
                "id": "noten_a5",
                "label": "Noten A5",
                "printer_name": "A5",
                "dpi": 600,
                "rotate_degrees": 90,
                "normalize_page_size": "A5",
                "max_upscale_percent": 105,
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

    targets = resolve_plan_targets(
        printing,
        print_plan=[{"range": "Alle Seiten", "profile_id": "noten_a5"}],
    )

    assert len(targets) == 1
    assert targets[0].printer_name == "A5"
    assert targets[0].rotate_degrees == 90
    assert targets[0].normalize_page_size == "A5"
    assert targets[0].max_upscale_percent == 105


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

    # One job per copy (never one job with copies=N) so a single-row plan
    # still dispatches N independent, individually confirmable jobs.
    assert len(queue.jobs) == 3
    assert all(job.copies == 1 for job in queue.jobs)
    assert all(job.pages == [1, 2, 3] for job in queue.jobs)
    assert all(job.dpi == 600 for job in queue.jobs)
    assert all(job.printer_name == "Brochure" for job in queue.jobs)
    assert all(job.placement_mode == "calibrated" for job in queue.jobs)
    assert all(job.page_size == "A5" for job in queue.jobs)
    assert all(job.orientation == "portrait" for job in queue.jobs)
    assert all(job.scale_mode == "fit" for job in queue.jobs)
    assert all(job.alignment == "center" for job in queue.jobs)
    assert all(job.x_offset_mm == -2.0 for job in queue.jobs)
    assert all(job.y_offset_mm == 0.5 for job in queue.jobs)
    assert all(job.render_color_mode == "gray" for job in queue.jobs)
    assert all(job.black_enhancement == "threshold" for job in queue.jobs)
    assert all(job.black_threshold == 200 for job in queue.jobs)
    assert all(job.backend == "pdf_xchange" for job in queue.jobs)
    assert all(job.native_pdf_exe == "C:/Program Files/PDFXEdit.exe" for job in queue.jobs)


def test_print_pdf_by_plan_interleaves_copies_across_plan_rows() -> None:
    """Regression test for XW-6612: copies must come off as complete sets.

    Before this fix, a 3-row plan printed all N copies of row 1, then all N
    copies of row 2, then all N copies of row 3 — forcing the user to
    re-collate the piece by hand. Copies must instead cycle through every
    row before repeating, in plan order.
    """
    printing = _printing_config()
    queue = _QueueStub()

    print_pdf_by_plan(
        "C:/tmp/test.pdf",
        printing,
        print_plan=[
            {"range": "1-2", "profile_id": "noten_simplex"},
            {"range": "3-END", "profile_id": "noten_duplex"},
        ],
        page_count=5,
        copies=3,
        print_queue=queue,  # type: ignore[arg-type]
    )

    assert [(job.printer_name, job.pages) for job in queue.jobs] == [
        ("Simplex", [0, 1]),
        ("Duplex", [2, 3, 4]),
        ("Simplex", [0, 1]),
        ("Duplex", [2, 3, 4]),
        ("Simplex", [0, 1]),
        ("Duplex", [2, 3, 4]),
    ]
    assert all(job.copies == 1 for job in queue.jobs)


def test_print_pdf_by_plan_keeps_different_printers_for_multiple_rows() -> None:
    printing = _printing_config()
    queue = _QueueStub()

    print_pdf_by_plan(
        "C:/tmp/test.pdf",
        printing,
        print_plan=[
            {"range": "1-2", "profile_id": "noten_simplex"},
            {"range": "3-END", "profile_id": "noten_duplex"},
        ],
        page_count=5,
        print_queue=queue,  # type: ignore[arg-type]
    )

    assert [(job.printer_name, job.pages) for job in queue.jobs] == [
        ("Simplex", [0, 1]),
        ("Duplex", [2, 3, 4]),
    ]


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
    assert target.rotate_degrees == 0
    assert target.render_color_mode == "auto"
    assert target.black_enhancement == "auto"
    assert target.black_threshold == 180
    assert target.backend == "qt_raster"
    assert target.native_pdf_exe == ""


class _WaitQueueStub:
    """Fake queue whose ``fail_at``-th job (1-based) reports failure."""

    def __init__(self, fail_at: int) -> None:
        self.jobs: list[PdfPrintJob] = []
        self._fail_at = fail_at

    def enqueue(self, job: PdfPrintJob) -> str:
        self.jobs.append(job)
        return job.id

    def enqueue_and_wait(self, job: PdfPrintJob, *, timeout_seconds: float = 300.0) -> PrintJobResult:
        self.jobs.append(job)
        success = len(self.jobs) != self._fail_at
        return PrintJobResult(
            job_id=job.id,
            success=success,
            description="",
            printer_name=job.printer_name,
            message="" if success else "Drucker offline",
        )


def test_print_pdf_by_plan_reports_completed_copies_on_partial_failure() -> None:
    """A failure mid-batch must report whole sets already confirmed.

    With two plan rows and the 4th dispatched job failing (copy index 1,
    row index 1 — i.e. the second row of the second set), exactly one full
    set (copy 0, both rows) was already confirmed before the failure.
    """
    printing = _printing_config()
    queue = _WaitQueueStub(fail_at=4)

    with pytest.raises(PrintPlanPartialFailure) as exc_info:
        print_pdf_by_plan(
            "C:/tmp/test.pdf",
            printing,
            print_plan=[
                {"range": "1-2", "profile_id": "noten_simplex"},
                {"range": "3-END", "profile_id": "noten_duplex"},
            ],
            page_count=5,
            copies=3,
            print_queue=queue,  # type: ignore[arg-type]
            wait=True,
        )

    assert exc_info.value.completed_copies == 1
    assert "Drucker offline" in str(exc_info.value)
    assert len(queue.jobs) == 4


def test_unknown_backend_is_rejected_during_plan_resolution() -> None:
    printing = PrintingSection(
        print_profiles=[{"id": "broken", "printer_name": "P", "backend": "magic"}]
    )

    with pytest.raises(RuntimeError, match="Unbekanntes PDF-Druckbackend"):
        resolve_plan_targets(printing, profile_id="broken")
