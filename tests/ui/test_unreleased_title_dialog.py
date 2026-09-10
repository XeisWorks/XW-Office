from __future__ import annotations

from xw_office.services.products.catalog import ProductCatalogService
from xw_office.ui.dialogs.unreleased_title_dialog import (
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
