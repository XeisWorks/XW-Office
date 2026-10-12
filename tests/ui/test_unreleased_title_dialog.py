from __future__ import annotations

from xw_office.services.products.catalog import ProductCatalogService
from xw_office.ui.dialogs.unreleased_title_dialog import (
    UnreleasedCatalogDialog,
    UnreleasedProductEditDialog,
    UnreleasedTitleDialog,
    UnreleasedTitleSplitDialog,
)


def test_unreleased_title_dialog_preselects_alias_target_and_owner(qtbot: object) -> None:
    catalog = ProductCatalogService()
    catalog.save_unreleased_resolution(
        "Alias aus Wix",
        canonical_name="Kanonischer Titel",
        owner="Krickl",
    )

    dialog = UnreleasedTitleDialog(catalog, raw_title="Alias aus Wix")
    qtbot.addWidget(dialog)

    assert dialog._title.isReadOnly()  # noqa: SLF001
    assert dialog._canonical.currentText() == "Kanonischer Titel"  # noqa: SLF001
    assert dialog._owner.currentText() == "Krickl"  # noqa: SLF001


def test_title_split_dialog_requires_one_line_per_ordered_piece(qtbot: object) -> None:
    dialog = UnreleasedTitleSplitDialog(quantity=2, initial_text="Nur ein Titel")
    qtbot.addWidget(dialog)

    dialog._validate_and_accept()  # noqa: SLF001
    assert "genau 2 Titel" in dialog._error.text()  # noqa: SLF001

    dialog._titles.setPlainText("Titel A\nTitel B")  # noqa: SLF001
    dialog._validate_and_accept()  # noqa: SLF001
    assert dialog.result() == dialog.DialogCode.Accepted


def test_unreleased_product_edit_dialog_prefills_and_accepts(qtbot: object) -> None:
    catalog = ProductCatalogService()
    dialog = UnreleasedProductEditDialog(
        catalog,
        canonical_name="Gabriellas Song XXL",
        owner="Albert",
        aliases=["Gabriellas Song (XXL Version)"],
        title="Unreleased-Produkt erfassen (Gabriellas Song (XXL Version))",
    )
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Unreleased-Produkt erfassen (Gabriellas Song (XXL Version))"
    assert dialog._name_input.text() == "Gabriellas Song XXL"  # noqa: SLF001
    assert dialog._owner_combo.currentText() == "Albert"  # noqa: SLF001
    assert "Gabriellas Song (XXL Version)" in dialog._aliases_input.toPlainText()  # noqa: SLF001

    dialog._validate_and_accept()  # noqa: SLF001
    assert dialog.result() == dialog.DialogCode.Accepted

    name, owner, aliases = dialog.get_data()
    assert name == "Gabriellas Song XXL"
    assert owner == "Albert"
    assert aliases == ["Gabriellas Song (XXL Version)"]

