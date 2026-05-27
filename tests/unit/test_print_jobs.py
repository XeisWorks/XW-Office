from __future__ import annotations

from xw_studio.services.printing.print_jobs import PdfPrintJob


def test_pdf_print_job_defaults_dpi_by_kind() -> None:
    assert PdfPrintJob(pdf_path="a.pdf", printer_name="P", job_kind="music").effective_dpi == 600
    assert PdfPrintJob(pdf_path="a.pdf", printer_name="P", job_kind="product").effective_dpi == 600
    assert PdfPrintJob(pdf_path="a.pdf", printer_name="P", job_kind="invoice").effective_dpi == 300
    assert PdfPrintJob(pdf_path="a.pdf", printer_name="P", job_kind="label").effective_dpi == 300


def test_pdf_print_job_profile_dpi_overrides_default() -> None:
    job = PdfPrintJob(pdf_path="a.pdf", printer_name="P", job_kind="product", dpi=450)

    assert job.effective_dpi == 450


def test_pdf_print_job_default_placement_is_paper_origin() -> None:
    job = PdfPrintJob(pdf_path="a.pdf", printer_name="P")

    assert job.placement_mode == "paper_origin"
    assert job.x_offset_mm == 0.0
    assert job.y_offset_mm == 0.0
