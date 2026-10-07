"""Focused layout tests for the commission workspace."""

from __future__ import annotations

from xw_office.services.calculation.service import CalculationService
from xw_office.services.commission.service import CommissionProfile, CommissionService
from xw_office.ui.modules.calculation.view import CalculationView


class _CommissionServiceStub:
    def __init__(self) -> None:
        self.profile = CommissionProfile(
            key="musikheroes",
            label="MusikHeroes",
            category_names=("MusikHeroes",),
        )

    def list_profiles(self) -> list[CommissionProfile]:
        return [self.profile]

    def get_profile(self, _key: str) -> CommissionProfile:
        return self.profile


class _CalculationServiceStub:
    def load_articles(self) -> list[object]:
        return []


class _ContainerStub:
    def __init__(self) -> None:
        self.commission = _CommissionServiceStub()
        self.calculation = _CalculationServiceStub()

    def resolve(self, service_type: type[object]) -> object:
        if service_type is CommissionService:
            return self.commission
        if service_type is CalculationService:
            return self.calculation
        raise KeyError(service_type)


def test_commission_view_uses_compact_tables_and_collapsed_documents(qtbot: object) -> None:
    view = CalculationView(_ContainerStub())  # type: ignore[arg-type]
    qtbot.addWidget(view)

    assert view._product_table._model._columns == ["Name", "Verkauft", "Netto"]  # noqa: SLF001
    assert view._category_table._model._columns == [  # noqa: SLF001
        "Kategorie",
        "Menge",
        "Netto",
        "Brutto",
    ]
    assert not view._documents_group.isChecked()  # noqa: SLF001
    assert view._doc_table.isHidden()  # noqa: SLF001
