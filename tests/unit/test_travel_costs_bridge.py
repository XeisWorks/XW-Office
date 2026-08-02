"""Tests for optional Reisekosten bridge loading."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QLabel

from xw_office.ui.modules.travel_costs.view import load_travel_costs_widget


def test_load_travel_costs_widget_from_factory(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "reisekosten.bridge":
            return SimpleNamespace(create_widget=lambda: QLabel("ok"))
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("xw_office.ui.modules.travel_costs.view.importlib.import_module", fake_import)

    widget, attempts = load_travel_costs_widget()

    assert widget is not None
    assert widget.__class__.__name__ == "QLabel"
    assert isinstance(attempts, list)


def test_load_travel_costs_widget_returns_none_when_missing(monkeypatch) -> None:
    def fake_import(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("xw_office.ui.modules.travel_costs.view.importlib.import_module", fake_import)

    widget, attempts = load_travel_costs_widget()

    assert widget is None
    assert attempts
