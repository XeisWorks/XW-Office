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
