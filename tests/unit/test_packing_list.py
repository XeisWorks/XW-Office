from __future__ import annotations

import fitz

from xw_office.services.plc.packing_list import PackingListContext, PackingListItem, PackingListService


def test_two_portrait_a6_packing_lists_share_one_landscape_a5_page(tmp_path) -> None:
    contexts = (
        PackingListContext(
            reference="21104",
            invoice_number="RE-21104",
            customer_name="Ada Example",
            package_number=1,
            package_count=2,
            weight_kg=0.41,
            items=(PackingListItem(quantity=22, display_quantity="20+2", name="Notenheft", sku="NH-1"),),
        ),
        PackingListContext(
            reference="21104",
            invoice_number="RE-21104",
            customer_name="Ada Example",
            package_number=2,
            package_count=2,
            weight_kg=0.32,
            items=(PackingListItem(quantity=1, name="Partitur", sku="PT-2"),),
        ),
    )

    pdf_path = PackingListService().generate_pdf(contexts, output_dir=tmp_path)

    document = fitz.open(pdf_path)
    assert len(document) == 1
    assert document[0].rect.width == fitz.paper_size("a5")[1]
    assert document[0].rect.height == fitz.paper_size("a5")[0]
    text = document[0].get_text()
    assert text.count("PACKLISTE") == 2
    assert "PAKET 1 VON 2" in text
    assert "PAKET 2 VON 2" in text
    assert "20+2" in text
    assert "Notenheft" in text
    assert "Partitur" in text


def test_packing_list_compacts_rows_when_more_than_eight_items_are_assigned(tmp_path) -> None:
    items = tuple(PackingListItem(quantity=1, name=f"Artikel {number}", sku=f"XW-{number}") for number in range(1, 11))
    context = PackingListContext(
        reference="21104",
        invoice_number="RE-21104",
        customer_name="Ada Example",
        package_number=1,
        package_count=1,
        weight_kg=1.2,
        items=items,
    )

    pdf_path = PackingListService().generate_pdf((context,), output_dir=tmp_path)

    document = fitz.open(pdf_path)
    text = document[0].get_text()
    assert "Artikel 1" in text
    assert "Artikel 10" in text
