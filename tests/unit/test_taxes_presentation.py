"""Headless tests for read-only UVA presentation, without services or network calls."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, cast
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout
from pytestqt.qtbot import QtBot

from xw_office.core.container import Container
from xw_office.ui.modules.taxes.presentation import UvaPresentation, format_euro, validate_preview
from xw_office.ui.modules.taxes.view import TaxesView


class _UvaOnlyTaxesView(TaxesView):
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_uva_tab())


@pytest.fixture
def tax_view(qtbot: QtBot) -> _UvaOnlyTaxesView:
    service = Mock()
    service.describe_capabilities.return_value = "UVA-Test"
    container = Mock()
    container.resolve.return_value = service
    view = _UvaOnlyTaxesView(cast(Container, container))
    qtbot.addWidget(view)
    view.resize(1000, 950)
    view.show()
    return view


@pytest.fixture
def payload() -> dict[str, Any]:
    return {
        "zahlbetrag": "31.75",
        "preview": {
            "year": 2026,
            "month": 8,
            "sales": {
                "total_vat": "43.25",
                "total_gross": "543.25",
                "total_net": "500.00",
                "groups": [
                    {
                        "label": "MIT 10% MEHRWERTSTEUER",
                        "vat_amount": "13.25",
                        "gross_amount": "145.75",
                        "net_amount": "132.50",
                    },
                    {
                        "label": "STEUERFREIE INNERGEMEINSCHAFTLICHE LIEFERUNG (EU)",
                        "vat_amount": "0.00",
                        "gross_amount": "217.50",
                        "net_amount": "217.50",
                    },
                    {
                        "label": "Ausländische Umsatzsteuer <Test>",
                        "vat_amount": "30.00",
                        "gross_amount": "180.00",
                        "net_amount": "150.00",
                    },
                ],
            },
            "input_tax": {
                "total_vat": "11.50",
                "total_gross": "111.50",
                "total_net": "100.00",
                "groups": [
                    {
                        "label": "Ausländische Vorsteuer",
                        "vat_amount": "4.50",
                        "gross_amount": "54.50",
                        "net_amount": "50.00",
                    },
                    {
                        "label": "Inländische Vorsteuer",
                        "vat_amount": "7.00",
                        "gross_amount": "57.00",
                        "net_amount": "50.00",
                    },
                ],
            },
            "warnings": ["Teilzahlung anteilig: Testbeleg"],
        },
        "kennzahlen": {"A022": "150.00", "A029": "132.50", "C060": "7.00"},
        "kennzahlen_text": (
            "UVA-Kennzahlen\nA022: EUR 150,00\n\nHinweise:\n"
            "- Teilzahlung anteilig: Testbeleg"
        ),
        "preview_text": "LEGACY_PREVIEW_SHOULD_NOT_APPEAR",
        "warnings": ["Teilzahlung anteilig: Testbeleg", "  Teilzahlung anteilig: Testbeleg "],
        "data_quality": {
            "status": "ZM-UID pruefen",
            "blocking_count": 1,
            "uva_blocking_count": 0,
            "zm_blocking_count": 1,
            "blocking": ["UID des Testkunden fehlt"],
            "warning_count": 1,
            "warnings": ["Teilzahlung anteilig: Testbeleg"],
        },
        "cache": {"hit": True, "source": "persistent", "snapshot_hash": "test-cache-id"},
        "reference_comparison": {"marker": "REFERENCE_SHOULD_NOT_APPEAR"},
        "zm_text": "ZM: Testkunde",
    }


def _presentation(view: TaxesView) -> UvaPresentation:
    assert view._uva_presentation is not None
    return view._uva_presentation


def test_exact_preview_totals_all_groups_and_no_payload_mutation(
    tax_view: _UvaOnlyTaxesView, payload: dict[str, Any]
) -> None:
    original = deepcopy(payload)
    tax_view._set_uva_payload(payload)
    presentation = _presentation(tax_view)
    text = presentation.summary.toPlainText()
    assert "Mehrwertsteuer" in text
    assert "Vorsteuer" in text
    for section_name in ("sales", "input_tax"):
        section = payload["preview"][section_name]
        for key in ("total_vat", "total_gross", "total_net"):
            assert f"EUR {section[key].replace('.', ',')}" in text
        for group in section["groups"]:
            assert group["label"] in text
            for key in ("vat_amount", "gross_amount", "net_amount"):
                assert f"EUR {group[key].replace('.', ',')}" in text
    assert tax_view._uva_amount_label is not None
    assert tax_view._uva_amount_label.text() == "EUR 31,75"
    assert tax_view._zm_output is not None
    assert tax_view._zm_output.toPlainText() == payload["zm_text"]
    assert payload == original
    assert "LEGACY_PREVIEW_SHOULD_NOT_APPEAR" not in text
    assert "REFERENCE_SHOULD_NOT_APPEAR" not in text
    assert "A022" not in text


def test_warnings_and_diagnostics_collapsed_but_blockers_persist(
    qtbot: QtBot, tax_view: _UvaOnlyTaxesView, payload: dict[str, Any]
) -> None:
    tax_view._set_uva_payload(payload)
    presentation = _presentation(tax_view)
    assert set(presentation.details) == {"warnings", "data_quality", "cache", "kennzahlen"}
    assert presentation.status.isVisible()
    assert presentation.status.text() == "Abgabe blockiert: 1 Blocker (UVA: 0, ZM: 1)"
    for detail in presentation.details.values():
        assert detail.toggle.isVisible()
        assert not detail.toggle.isChecked()
        assert not detail.content.isVisible()
    warnings = presentation.details["warnings"]
    assert warnings.toggle.text() == "Hinweise (1)"
    assert warnings.content.toPlainText().count("Teilzahlung anteilig: Testbeleg") == 1
    assert "Teilzahlung anteilig" not in presentation.summary.toPlainText()
    assert "Teilzahlung anteilig" not in presentation.details["kennzahlen"].content.toPlainText()
    qtbot.mouseClick(warnings.toggle, Qt.MouseButton.LeftButton)
    assert warnings.content.isVisible()
    quality = presentation.details["data_quality"]
    qtbot.mouseClick(quality.toggle, Qt.MouseButton.LeftButton)
    assert quality.content.isVisible()
    assert "UID des Testkunden fehlt" in quality.content.toPlainText()
    qtbot.mouseClick(quality.toggle, Qt.MouseButton.LeftButton)
    assert not quality.content.isVisible()
    assert presentation.status.isVisible()


def test_refresh_replaces_totals_status_and_details(
    tax_view: _UvaOnlyTaxesView, payload: dict[str, Any]
) -> None:
    tax_view._set_uva_payload(payload)
    presentation = _presentation(tax_view)
    presentation.details["warnings"].toggle.setChecked(True)
    refreshed = deepcopy(payload)
    refreshed["zahlbetrag"] = "-12.00"
    refreshed["preview"]["sales"]["total_vat"] = "9.00"
    refreshed["preview"]["sales"]["groups"] = []
    refreshed["preview"]["warnings"] = []
    refreshed["warnings"] = []
    refreshed["kennzahlen_text"] = "A022: EUR 0,00"
    refreshed["data_quality"] = {"status": "abgabebereit", "blocking_count": 0}
    refreshed["zm_text"] = "Neue ZM"
    original = deepcopy(refreshed)
    tax_view._set_uva_payload(refreshed)
    text = presentation.summary.toPlainText()
    assert "EUR 9,00" in text
    assert "EUR 43,25" not in text
    assert "Ausländische Umsatzsteuer" not in text
    assert presentation.status.text() == "Abgabestatus: abgabebereit · 0 Blocker"
    assert presentation.details["warnings"].toggle.text() == "Hinweise (0)"
    assert not presentation.details["warnings"].content.isVisible()
    assert tax_view._uva_amount_label is not None
    assert tax_view._uva_amount_label.text() == "EUR -12,00"
    assert refreshed == original


def test_invalid_preview_does_not_reuse_stale_or_unvalidated_text(
    tax_view: _UvaOnlyTaxesView, payload: dict[str, Any]
) -> None:
    tax_view._set_uva_payload(payload)
    invalid = deepcopy(payload)
    del invalid["preview"]["sales"]["total_net"]
    assert validate_preview(invalid["preview"]) is None
    tax_view._set_uva_payload(invalid)
    presentation = _presentation(tax_view)
    assert "Keine gültige Steuervorschau" in presentation.summary.toPlainText()
    assert "EUR 43,25" not in presentation.summary.toPlainText()
    assert "LEGACY_PREVIEW" not in presentation.summary.toPlainText()
    assert "1 Blocker" in presentation.status.text()


@pytest.mark.parametrize(
    ("quality", "expected"),
    [
        ({"uva_blocking": ["Beleg fehlt"]}, "1 Blocker (UVA: 1, ZM: 0)"),
        ({"blocking": ["Beleg fehlt", "UID fehlt"]}, "2 Blocker"),
        ({"status": "blockiert"}, "blockierende Prüfung erforderlich"),
        (None, "noch nicht geprüft"),
    ],
)
def test_blockers_not_hidden_by_missing_or_inconsistent_counts(
    tax_view: _UvaOnlyTaxesView, payload: dict[str, Any], quality: object, expected: str
) -> None:
    payload["data_quality"] = quality
    tax_view._set_uva_payload(payload)
    status = _presentation(tax_view).status
    assert status.isVisible()
    assert expected in status.text()


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("12456.78", "12 456,78"), ("-1234.50", "-1 234,50"), ("0", "0,00")],
)
def test_euro_formatting(amount: str, expected: str) -> None:
    assert format_euro(amount) == expected
