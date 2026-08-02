"""Tests for royalty calculation helpers."""
from __future__ import annotations

import json

from xw_office.services.calculation.service import (
    ArticleEntry,
    CalculationService,
    calculate_royalty,
)


class _RepoStub:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.values = initial or {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self.values[key] = value_json


def test_calculate_royalty_breaks_down_gross() -> None:
    result = calculate_royalty(22.0, vat_pct=10.0, royalty_pct=20.0)

    assert round(result.net, 2) == 20.0
    assert round(result.vat_amount, 2) == 2.0
    assert round(result.royalty_amount, 2) == 4.0
    assert round(result.net_after_royalty, 2) == 16.0


def test_load_articles_reads_json_from_repository() -> None:
    repo = _RepoStub(
        {
            "calculation.articles": json.dumps(
                [
                    {
                        "title": "Chorheft A",
                        "gross_price": 19.9,
                        "vat_pct": 10,
                        "royalty_pct": 12.5,
                        "note": "Standard",
                    }
                ]
            )
        }
    )
    service = CalculationService(repo)

    articles = service.load_articles()

    assert len(articles) == 1
    assert articles[0] == ArticleEntry(
        title="Chorheft A",
        gross_price=19.9,
        vat_pct=10.0,
        royalty_pct=12.5,
        note="Standard",
    )


def test_save_articles_persists_json() -> None:
    repo = _RepoStub()
    service = CalculationService(repo)

    service.save_articles(
        [
            ArticleEntry(
                title="Werk B",
                gross_price=15.5,
                vat_pct=20.0,
                royalty_pct=8.0,
                note="Export",
            )
        ]
    )

    payload = json.loads(repo.values["calculation.articles"])
    assert payload == [
        {
            "title": "Werk B",
            "gross_price": 15.5,
            "vat_pct": 20.0,
            "royalty_pct": 8.0,
            "note": "Export",
        }
    ]