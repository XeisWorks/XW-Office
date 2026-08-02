from __future__ import annotations

from pathlib import Path

from xw_office.services.products.catalog import Product, ProductCatalogService
from xw_office.services.products.pdf_bulk_mapper import PdfBulkMapper, ProductMatch


def test_bulk_mapper_auto_matches_and_applies(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "Brandlalm Boarischer_A4_2x.pdf").write_bytes(b"%PDF-1.4\n")
    (pdf_dir / "Unrelated Piece.pdf").write_bytes(b"%PDF-1.4\n")

    catalog = ProductCatalogService()
    catalog._by_sku["XW-7001"] = Product(
        id="p1",
        sku="XW-7001",
        name="Brandlalm Boarischer",
        is_digital=False,
    )

    result = PdfBulkMapper.scan(pdf_dir, catalog)

    assert result.scanned_pdf_count == 2
    assert len(result.auto_matches) == 1
    assert result.auto_matches[0].sku == "XW-7001"

    updated = PdfBulkMapper.apply(result.auto_matches, catalog)
    assert updated == 1
    assert catalog.get_by_sku("XW-7001") is not None
    assert str(catalog.get_by_sku("XW-7001").print_file_path).endswith("Brandlalm Boarischer_A4_2x.pdf")


def test_bulk_mapper_keeps_existing_path_unless_overwrite(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "Another Name.pdf").write_bytes(b"%PDF-1.4\n")

    catalog = ProductCatalogService()
    catalog._by_sku["XW-7002"] = Product(
        id="p2",
        sku="XW-7002",
        name="Test Product",
        is_digital=False,
        print_file_path="C:/already/set.pdf",
    )

    result_no_overwrite = PdfBulkMapper.scan(pdf_dir, catalog, overwrite_existing=False)
    assert "XW-7002" in result_no_overwrite.already_configured

    result_overwrite = PdfBulkMapper.scan(pdf_dir, catalog, overwrite_existing=True)
    # With overwrite=true we at least evaluate this SKU (may end up review or auto)
    assert "XW-7002" not in result_overwrite.already_configured


def test_apply_supports_manual_review_confirmation() -> None:
    catalog = ProductCatalogService()
    catalog._by_sku["XW-7003"] = Product(
        id="p3",
        sku="XW-7003",
        name="Manual Product",
        is_digital=False,
    )

    manual = [
        ProductMatch(
            sku="XW-7003",
            product_name="Manual Product",
            pdf_path="D:/scores/Manual Product.pdf",
            score=0.61,
            is_auto=False,
        )
    ]

    updated = PdfBulkMapper.apply(manual, catalog)
    assert updated == 1
    assert catalog.get_by_sku("XW-7003").print_file_path == "D:/scores/Manual Product.pdf"
