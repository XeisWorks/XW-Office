from __future__ import annotations

from xw_office.services.draft_invoice.service import ProductDraft, ProductIssue
from xw_office.ui.modules.rechnungen.product_preflight_dialog import ProductPreflightDialog


def test_product_preflight_displays_wix_gross_price_in_german_currency_format(qtbot: object) -> None:
    issue = ProductIssue(
        sku="XW-100",
        wix_name="Produkt Eins",
        wix_order_number="20519",
        wix_description="Wix-Text",
        wix_price_gross=1234.5,
        is_digital=False,
        draft=ProductDraft(
            name="Produkt Eins",
            sku="XW-100",
            text="[Mnozil]",
            internal_comment="",
            price_gross=1234.5,
            tax_rate=19.0,
            unity={"id": 1, "objectName": "Unity"},
            category_id="CAT-1",
            category_name="Mnozil",
        ),
    )
    dialog = ProductPreflightDialog(issue, part_categories=[{"id": "CAT-1", "name": "Mnozil"}])
    qtbot.addWidget(dialog)

    assert dialog._price.text() == "€ 1.234,50"  # noqa: SLF001
    assert dialog._description.toPlainText() == "[Mnozil]"  # noqa: SLF001
    assert ProductPreflightDialog._parse_optional_float("€ 1.234,50") == 1234.5
