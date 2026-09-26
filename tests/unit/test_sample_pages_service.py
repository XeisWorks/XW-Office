from __future__ import annotations

import fitz
import pytest
from PIL import Image

from xw_office.services.layout.sample_pages_models import (
    SamplePageExportError,
    SamplePageExportSettings,
    SamplePageJob,
    parse_page_numbers,
)
from xw_office.services.layout.sample_pages_service import SamplePageExportService


def _make_pdf(tmp_path, page_count: int, name: str = "test.pdf"):
    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page(width=595, height=842)  # A4 portrait in points
        page.insert_text((72, 72), f"Seite {index + 1}")
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def test_parse_page_numbers_supports_commas_and_ranges() -> None:
    assert parse_page_numbers("1,5,7", page_count=10) == (1, 5, 7)
    assert parse_page_numbers("8-10,2", page_count=10) == (2, 8, 9, 10)


def test_parse_page_numbers_rejects_out_of_range() -> None:
    with pytest.raises(SamplePageExportError, match="außerhalb"):
        parse_page_numbers("1,99", page_count=10)


def test_parse_page_numbers_rejects_empty_and_garbage() -> None:
    with pytest.raises(SamplePageExportError):
        parse_page_numbers("", page_count=10)
    with pytest.raises(SamplePageExportError):
        parse_page_numbers("abc", page_count=10)


def test_export_renders_expected_height_and_filenames(tmp_path) -> None:
    pdf_path = _make_pdf(tmp_path, page_count=3, name="Programmheft.pdf")
    output_folder = tmp_path / "out"
    service = SamplePageExportService()

    results = service.export(
        [SamplePageJob(pdf_path=pdf_path, pages=(1, 3))],
        SamplePageExportSettings(output_folder=output_folder, target_height_px=400, max_size_kb=200),
    )

    assert [r.page_number for r in results] == [1, 3]
    names = {r.output_path.name for r in results}
    assert names == {"Programmheft_S1.jpg", "Programmheft_S3.jpg"}
    for result in results:
        assert result.output_path.is_file()
        with Image.open(result.output_path) as img:
            assert img.height == 400
        assert result.file_size_bytes <= 200 * 1024


def test_export_avoids_overwriting_existing_file(tmp_path) -> None:
    pdf_path = _make_pdf(tmp_path, page_count=1, name="A.pdf")
    output_folder = tmp_path / "out"
    output_folder.mkdir()
    (output_folder / "A_S1.jpg").write_bytes(b"existing")
    service = SamplePageExportService()

    results = service.export(
        [SamplePageJob(pdf_path=pdf_path, pages=(1,))],
        SamplePageExportSettings(output_folder=output_folder),
    )

    assert results[0].output_path.name == "A_S1 (2).jpg"


def test_export_rejects_page_out_of_range(tmp_path) -> None:
    pdf_path = _make_pdf(tmp_path, page_count=1, name="A.pdf")
    service = SamplePageExportService()

    with pytest.raises(SamplePageExportError, match="hat nur"):
        service.export(
            [SamplePageJob(pdf_path=pdf_path, pages=(5,))],
            SamplePageExportSettings(output_folder=tmp_path / "out"),
        )


def test_export_applies_half_cut_watermark_to_selected_pages(tmp_path) -> None:
    pdf_path = _make_pdf(tmp_path, page_count=2, name="A.pdf")
    with fitz.open(pdf_path) as doc:
        for page in doc:
            page.draw_rect(page.rect, color=None, fill=(1, 0, 0), overlay=False)
        doc.save(tmp_path / "red.pdf")

    watermark_path = tmp_path / "watermark.png"
    Image.new("RGBA", (120, 30), (0, 0, 255, 255)).save(watermark_path)
    service = SamplePageExportService()

    results = service.export(
        [SamplePageJob(pdf_path=tmp_path / "red.pdf", pages=(1,), watermarked_pages=(2,))],
        SamplePageExportSettings(
            output_folder=tmp_path / "out",
            target_height_px=400,
            max_size_kb=200,
            watermark_path=watermark_path,
        ),
    )

    assert [result.is_watermarked for result in results] == [False, True]
    with Image.open(results[1].output_path) as image:
        # The lower-right triangle is lightened by the half-cut overlay.
        assert image.getpixel((image.width - 5, image.height - 5))[1] > 180


def test_export_rejects_pages_selected_in_both_output_modes(tmp_path) -> None:
    pdf_path = _make_pdf(tmp_path, page_count=1)

    with pytest.raises(SamplePageExportError, match="sowohl normal"):
        SamplePageExportService().export(
            [SamplePageJob(pdf_path=pdf_path, pages=(1,), watermarked_pages=(1,))],
            SamplePageExportSettings(output_folder=tmp_path / "out"),
        )
