from __future__ import annotations

from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from xw_office.services.layout.service import (  # noqa: E402
    LayoutToolsService,
    _build_a5_target_rects,
)


def _build_source_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        for index in range(3):
            if index < 2:
                page = doc.new_page(width=595, height=420)
                page.draw_rect(fitz.Rect(20, 20, 575, 400), color=(0, 0, 0), width=4)
                page.insert_text((40, 70), f"Page {index + 1}", fontsize=28)
            else:
                page = doc.new_page(width=400, height=575)
                page.draw_rect(fitz.Rect(20, 20, 380, 555), color=(0, 0, 0), width=4)
                page.insert_text((40, 80), "ROTATED PAGE 3", fontsize=28)
                page.draw_rect(fitz.Rect(35, 120, 185, 210), color=(1, 0, 0), fill=(1, 0, 0))
                page.draw_rect(fitz.Rect(220, 340, 360, 520), color=(0, 0, 1), fill=(0, 0, 1))
                page.set_rotation(270)
        doc.save(path)
    finally:
        doc.close()


def _build_landscape_split_source_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=500)
        page.insert_text((40, 80), "COVER", fontsize=28)

        page = doc.new_page(width=1000, height=500)
        page.draw_rect(fitz.Rect(0, 0, 500, 500), color=(1, 0, 0), fill=(1, 0, 0))
        page.draw_rect(fitz.Rect(500, 0, 1000, 500), color=(0, 0, 1), fill=(0, 0, 1))

        page = doc.new_page(width=320, height=520)
        page.insert_text((40, 80), "END", fontsize=28)
        doc.save(path)
    finally:
        doc.close()


def _center_rgb(page: "fitz.Page") -> tuple[int, int, int]:
    rect = page.rect
    cx = rect.width / 2
    cy = rect.height / 2
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(1, 1),
        alpha=False,
        clip=fitz.Rect(cx, cy, cx + 1, cy + 1),
    )
    return tuple(pixmap.samples[:3])


def _content_bbox(page: "fitz.Page", clip: "fitz.Rect") -> tuple[int, int]:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False, clip=clip)
    samples = pixmap.samples
    width = pixmap.width
    height = pixmap.height
    stride = pixmap.n

    min_x = width
    min_y = height
    max_x = -1
    max_y = -1

    for y in range(height):
        row_offset = y * width * stride
        for x in range(width):
            idx = row_offset + x * stride
            if samples[idx] < 245 or samples[idx + 1] < 245 or samples[idx + 2] < 245:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if max_x < 0 or max_y < 0:
        return 0, 0
    return max_x - min_x + 1, max_y - min_y + 1


def test_duplicate_a5_to_a4_keeps_rotated_pages_readable(tmp_path: Path) -> None:
    source_path = tmp_path / "rotated-source.pdf"
    output_path = tmp_path / "rotated-source_A4-2x.pdf"
    _build_source_pdf(source_path)

    result = LayoutToolsService().duplicate_a5_to_a4(source_path, output_pdf=output_path)

    assert result == output_path
    with fitz.open(source_path) as source_doc:
        assert source_doc[2].rotation == 270
        assert source_doc[2].rect.width > source_doc[2].rect.height

    with fitz.open(output_path) as output_doc:
        assert len(output_doc) == 3
        assert output_doc[0].rect.width == pytest.approx(fitz.paper_size("a4")[0])
        assert output_doc[0].rect.height == pytest.approx(fitz.paper_size("a4")[1])

        page = output_doc[2]
        top_rect, bottom_rect = _build_a5_target_rects(fitz, page.rect.width, page.rect.height, 0.0)
        top_width, top_height = _content_bbox(page, top_rect)
        bottom_width, bottom_height = _content_bbox(page, bottom_rect)

    assert top_width > top_height
    assert bottom_width > bottom_height
    assert top_width > top_rect.width * 0.9
    assert bottom_width > bottom_rect.width * 0.9


def test_duplicate_a5_to_a4_refuses_existing_output_without_overwrite(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "source_A4-2x.pdf"
    _build_source_pdf(source_path)
    output_path.write_bytes(b"already here")

    with pytest.raises(FileExistsError):
        LayoutToolsService().duplicate_a5_to_a4(source_path, output_pdf=output_path)


def test_split_landscape_pages_to_a4_portrait_keeps_portrait_pages_unchanged(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "mixed.pdf"
    output_path = tmp_path / "mixed_A4-hoch-geteilt.pdf"
    _build_landscape_split_source_pdf(source_path)

    result = LayoutToolsService().split_landscape_pages_to_a4_portrait(
        source_path,
        output_pdf=output_path,
    )

    assert result.output_path == output_path
    assert result.source_pages == 3
    assert result.output_pages == 4
    assert result.split_pages == 1
    assert result.copied_pages == 2

    with fitz.open(output_path) as output_doc:
        assert len(output_doc) == 4
        assert output_doc[0].rect.width == pytest.approx(300)
        assert output_doc[0].rect.height == pytest.approx(500)
        assert output_doc[1].rect.width == pytest.approx(fitz.paper_size("a4")[0])
        assert output_doc[1].rect.height == pytest.approx(fitz.paper_size("a4")[1])
        assert output_doc[3].rect.width == pytest.approx(320)
        assert output_doc[3].rect.height == pytest.approx(520)

        left_rgb = _center_rgb(output_doc[1])
        right_rgb = _center_rgb(output_doc[2])

    assert left_rgb[0] > 200 and left_rgb[2] < 60
    assert right_rgb[2] > 200 and right_rgb[0] < 60
