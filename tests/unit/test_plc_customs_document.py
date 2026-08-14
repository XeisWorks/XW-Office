"""Tests for the calibrated PLC customs A5 derivative."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from xw_office.services.plc.customs_document import (
    AF_TARGET_RECT,
    PlcCustomsDocumentError,
    build_customs_a5_print_pdf,
    customs_a5_print_path,
    ensure_customs_a5_print_file,
)


SAMPLE = Path("resources/api_specs/plc/Zollerklaerung_TEST.pdf")


def test_sample_customs_pdf_becomes_af_a5_portrait_without_losing_pages() -> None:
    prepared = build_customs_a5_print_pdf(SAMPLE.read_bytes())

    document = fitz.open(stream=prepared, filetype="pdf")
    try:
        assert document.page_count == 1
        page = document[0]
        assert page.rect.width * 25.4 / 72 == pytest.approx(148.0, abs=0.05)
        assert page.rect.height * 25.4 / 72 == pytest.approx(210.0, abs=0.05)
        assert "XW-PLC-CUSTOMS-A5-AF" in document.metadata["producer"]

        content = _content_bbox(page)
        assert content.x0 == pytest.approx(AF_TARGET_RECT.x0, abs=0.2)
        assert content.y0 == pytest.approx(AF_TARGET_RECT.y0, abs=0.2)
        assert content.x1 == pytest.approx(AF_TARGET_RECT.x1, abs=0.2)
        assert content.y1 == pytest.approx(AF_TARGET_RECT.y1, abs=0.2)
    finally:
        document.close()


def test_multi_page_customs_pdf_keeps_every_page() -> None:
    source = fitz.open()
    for text in ("CN23 page one", "CN23 page two"):
        page = source.new_page(width=595, height=842)
        page.insert_text((20, 20), text)
        page.draw_rect(fitz.Rect(20, 20, 560, 450))
    raw = source.tobytes()
    source.close()

    prepared = fitz.open(stream=build_customs_a5_print_pdf(raw), filetype="pdf")
    try:
        assert prepared.page_count == 2
        assert all(page.rect.width < page.rect.height for page in prepared)
    finally:
        prepared.close()


def test_print_ready_file_is_persistent_and_not_transformed_twice(tmp_path: Path) -> None:
    original = tmp_path / "customs" / "20868 - RE-1 - Zollformular.pdf"
    original.parent.mkdir(parents=True)
    original.write_bytes(SAMPLE.read_bytes())

    prepared = ensure_customs_a5_print_file(original)

    assert prepared == customs_a5_print_path(original)
    assert prepared.parent == original.parent / "print_ready"
    assert prepared.is_file()
    assert ensure_customs_a5_print_file(prepared) == prepared
    assert original.read_bytes() == SAMPLE.read_bytes()


def test_invalid_customs_document_is_rejected() -> None:
    with pytest.raises(PlcCustomsDocumentError, match="PDF"):
        build_customs_a5_print_pdf(b"not a pdf")


def _content_bbox(page: fitz.Page) -> fitz.Rect:
    result = fitz.Rect()
    for kind, coordinates in page.get_bboxlog():
        if kind.startswith(("fill-", "stroke-")):
            result |= fitz.Rect(coordinates)
    return result
