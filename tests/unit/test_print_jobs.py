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


def test_music_and_product_jobs_default_to_gray_with_black_enhancement() -> None:
    music = PdfPrintJob(pdf_path="a.pdf", printer_name="P", job_kind="music")
    product = PdfPrintJob(pdf_path="a.pdf", printer_name="P", job_kind="product")
    invoice = PdfPrintJob(pdf_path="a.pdf", printer_name="P", job_kind="invoice")

    assert music.effective_render_color_mode == "auto"
    assert music.effective_black_enhancement == "auto_music"
    assert product.effective_render_color_mode == "auto"
    assert product.effective_black_enhancement == "auto_music"
    assert invoice.effective_render_color_mode == "rgb"
    assert invoice.effective_black_enhancement == "none"


def test_print_job_render_quality_can_be_overridden() -> None:
    job = PdfPrintJob(
        pdf_path="a.pdf",
        printer_name="P",
        job_kind="product",
        render_color_mode="rgb",
        black_enhancement="none",
    )

    assert job.effective_render_color_mode == "rgb"
    assert job.effective_black_enhancement == "none"
